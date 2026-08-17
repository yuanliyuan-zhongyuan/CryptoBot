import asyncio
import json
import ssl
import time
import aiohttp
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal
from dataclasses import asdict

from cryptotrade.core.adapters.websocket_manager import WebSocketManager
from cryptotrade.exchanges.cex.binance.base import BinanceBase
from cryptotrade.core.adapters.models import TickerData

try:
    import websockets
except ImportError:
    websockets = None


class BinanceWebSocket(WebSocketManager, BinanceBase):
    """
    Binance 专用 WebSocket 客户端 (双模版：支持 aiohttp 和 websockets)
    
    继承体系：
    - WebSocketManager: 提供连接管理、回调分发等通用 WebSocket 能力
    - BinanceBase: 提供 Binance 特有的配置解析、符号转换等基础能力
    
    兼容性设计：
    - 模式 1 (aiohttp): 当配置了 HTTP 代理 (proxy) 时自动启用。aiohttp 原生支持 HTTP 代理。
    - 模式 2 (websockets): 当未配置代理且安装了 websockets 库时启用。这是高性能的原生 WebSocket 实现。
    
    作用：
    - 根据配置中现货 / U 本位开关，自动选择合适的 WebSocket 节点
    - 建立与 Binance 的长连接，发送 SUBSCRIBE 订阅 bookTicker 流
    - 将 Binance 原始行情转换为统一字典，并通过 WebSocketManager._emit 向上层广播
    
    数据流：
    Binance WebSocket ➜ BinanceWebSocket._handle_message ➜ _emit(formatted)
    ➜ BinanceAdapter._on_ticker ➜ TradingCoordinator.on_ticker
    """

    def __init__(self, name: str, symbols: List[str], config: Optional[Dict[str, Any]] = None) -> None:
        # 初始化两个父类
        WebSocketManager.__init__(self, name=name)
        BinanceBase.__init__(self, config=config)
            
        self.symbols = symbols or []
        # 注意：self.config 已经在 BinanceBase.__init__ 中设置
        
        self._tasks: List[asyncio.Task] = []
        self._ws = None
        self._running = False
        self.session: Optional[aiohttp.ClientSession] = None
        
        # 覆盖 BinanceBase 的 ws_url (因为这里需要动态测速选择)
        self.ws_url: Optional[str] = None
        
        self.symbol_map: Dict[str, str] = {}
        for s in self.symbols:
            # 使用 BinanceBase 提供的通用方法
            norm = self.normalize_symbol(s)
            self.symbol_map[norm] = s

        # 智能选择后端
        # 1. 如果有代理 -> 强制使用 aiohttp (因为 websockets 代理支持较弱)
        # 2. 如果无代理且有 websockets 库 -> 使用 websockets (高性能)
        # 3. 否则 -> 使用 aiohttp (通用兜底)
        self.proxy_url = self.config.get("api", {}).get("proxy")
        
        if self.proxy_url:
            self.use_backend = "aiohttp"
            self.logger.info(f"🌐 检测到代理配置 {self.proxy_url}，自动切换至 aiohttp WebSocket 后端")
        elif websockets is not None:
            self.use_backend = "websockets"
            self.logger.info("⚡ 未检测到代理且 websockets 库可用，使用高性能 websockets 后端")
        else:
            self.use_backend = "aiohttp"
            self.logger.warning("⚠️ 未检测到 websockets 库，回退至 aiohttp WebSocket 后端")

    async def connect(self) -> None:
        """
        连接 WebSocket 并启动主循环
        """
        if self._running:
            return
        self._running = True
        
        if self.use_backend == "aiohttp" and not self.session:
            self.session = aiohttp.ClientSession()

        await self._select_best_ws_url()
        self.logger.info(f"🚀 [{self.name}] WebSocket ({self.use_backend}) 即将连接到 {self.ws_url}")
        self._tasks.append(asyncio.create_task(self._main_loop()))

    async def subscribe(
        self,
        channels: List[str],
        stream_type: str = "bookTicker",
        extra_stream_types: Optional[List[str]] = None,
    ) -> None:
        """
        订阅指定的频道 (channels 即 symbol 列表)

        :param channels: 交易对列表 (如 ['BTCUSDT', 'ETHUSDT'])
        :param stream_type: 主数据流类型，默认 bookTicker，可选 ticker (24h统计)
        :param extra_stream_types: 额外需要同时订阅的数据流类型列表（如 ['ticker']），
            用于一个 symbol 同时订阅高频 bookTicker + 低频 24hTicker
        """
        # 记录当前的流类型列表，供 _send_subscribe 使用
        streams = [stream_type]
        if extra_stream_types:
            for s in extra_stream_types:
                if s not in streams:
                    streams.append(s)
        self._current_stream_types = streams

        for s in channels:
            if s not in self.symbols:
                self.symbols.append(s)
                norm = self._normalize_symbol(s)
                self.symbol_map[norm] = s
        if self._ws:
            await self._send_subscribe()

    async def disconnect(self) -> None:
        """
        断开 WebSocket 连接并清理任务
        """
        if not self._running:
            return
        self._running = False
        
        # 关闭 WebSocket 连接
        if self._ws:
            try:
                if self.use_backend == "aiohttp":
                    await self._ws.close()
                elif self.use_backend == "websockets":
                    await self._ws.close()
            except Exception:
                pass
            self._ws = None
            
        # 关闭 aiohttp session
        if self.session:
            try:
                await self.session.close()
            except Exception:
                pass
            self.session = None

        for t in self._tasks:
            t.cancel()
        self._tasks = []
        self.logger.info(f"🛑 [{self.name}] WebSocket 已停止")

    async def _select_best_ws_url(self) -> None:
        """
        根据配置自动选择延迟最低的 WebSocket 节点 (并发测速)
        """
        api_conf = self.config.get("api", {})
        markets_conf = self.config.get("markets", {})
        use_usdm = bool(markets_conf.get("USD-M Futures", {}).get("enabled", False))
        env = api_conf.get("environment", "mainnet")
        if env == "testnet":
            if use_usdm:
                urls = api_conf.get("futures_market_ws_testnet_base_urls", []) or api_conf.get("testnet_ws_base_urls", [])
            else:
                urls = api_conf.get("ws_base_urls", [])
        else:
            if use_usdm:
                urls = api_conf.get("futures_market_ws_base_urls", []) or api_conf.get("futures_ws_base_urls", [])
            else:
                urls = api_conf.get("ws_base_urls", [])
        if not urls:
            self.logger.error("未找到任何 Binance WebSocket 配置 URL")
            return
        
        self.logger.info(f"🔍 [{self.name}] 正在并发优选最佳 WebSocket 节点...")
        
        # 确保 session 存在 (如果是 aiohttp 模式)
        if self.use_backend == "aiohttp" and not self.session:
            self.session = aiohttp.ClientSession()

        # 定义单次测速函数
        async def check_url(url: str) -> Tuple[str, float]:
            target = url
            if not target.endswith("/ws") and not target.endswith("/stream"):
                target += "/ws"
            
            try:
                start_t = time.monotonic()
                if self.use_backend == "aiohttp":
                    # 模式 1: aiohttp + Proxy
                    async with self.session.ws_connect(
                        target, 
                        proxy=self.proxy_url,
                        heartbeat=10,
                        ssl=False if self.proxy_url else None,
                        timeout=3.0 # 测速超时 3秒
                    ) as ws:
                        pass
                else:
                    # 模式 2: websockets (无代理)
                    async with websockets.connect(
                        target, 
                        close_timeout=1, 
                        open_timeout=3 # 测速超时 3秒
                    ) as ws:
                        pass
                
                latency = (time.monotonic() - start_t) * 1000
                return (target, latency)
            except Exception as e:
                # self.logger.debug(f"节点 {target} 连接失败: {e}")
                return (target, float("inf"))

        # 并发执行测速
        tasks = [check_url(url) for url in urls]
        results = await asyncio.gather(*tasks)

        best_url = None
        min_latency = float("inf")

        for target, latency in results:
            if latency < float("inf"):
                self.logger.info(f"  - 节点 {target} 延迟: {latency:.2f}ms")
                if latency < min_latency:
                    min_latency = latency
                    best_url = target
            else:
                self.logger.warning(f"  - 节点 {target} 连接超时或失败")

        if best_url:
            self.ws_url = best_url
            self.logger.info(f"✅ 选中最佳节点: {self.ws_url} (延迟 {min_latency:.2f}ms)")
        else:
            self.logger.error("⚠️ 所有节点测试失败，未能选出可用 Binance WebSocket 节点")

    async def _main_loop(self) -> None:
        """
        WebSocket 主循环 (双模式)
        """
        while self._running:
            try:
                if not self.ws_url:
                    await asyncio.sleep(1)
                    continue

                if self.use_backend == "aiohttp":
                    # === 模式 1: aiohttp 实现 ===
                    if not self.session:
                        self.session = aiohttp.ClientSession()

                    async with self.session.ws_connect(
                        self.ws_url, 
                        proxy=self.proxy_url,
                        heartbeat=20,
                        autoping=True
                    ) as ws:
                        self._ws = ws
                        self.logger.info(f"✅ [{self.name}] WebSocket (aiohttp) 已连接")
                        await self._send_subscribe()
                        
                        async for msg in ws:
                            if not self._running:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_message(msg.data)
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                break
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                break
                else:
                    # === 模式 2: websockets 实现 ===
                    connect_kwargs = {
                        "ping_interval": 20,
                        "ping_timeout": 20,
                        "close_timeout": 5
                    }
                    async with websockets.connect(self.ws_url, **connect_kwargs) as ws:
                        self._ws = ws
                        self.logger.info(f"✅ [{self.name}] WebSocket (websockets) 已连接")
                        await self._send_subscribe()
                        async for message in ws:
                            if not self._running:
                                break
                            await self._handle_message(message)
                            
            except Exception as e:
                self.logger.error(f"❌ [{self.name}] WebSocket 出错或断开: {e}")
                if self._running:
                    self.logger.info(f"🔄 [{self.name}] 5 秒后重试连接...")
                    await asyncio.sleep(5)

    async def _send_subscribe(self) -> None:
        """
        构造并发送订阅消息
        - 支持一次订阅多种数据流 (如同时 bookTicker + ticker_24h)
        """
        if not self._ws or not self.symbols:
            return

        # 获取当前 stream 列表 (兼容旧变量名)
        streams: List[str]
        if hasattr(self, "_current_stream_types"):
            streams = list(self._current_stream_types)
        elif hasattr(self, "_current_stream_type"):
            streams = [self._current_stream_type]
        else:
            streams = [self.BinanceStreamType.BOOK_TICKER.value]

        params: List[str] = []
        for s in self.symbols:
            norm = self.normalize_symbol(s).lower()
            for st in streams:
                params.append(f"{norm}@{st}")

        if not params:
            return

        payload = {
            "method": "SUBSCRIBE",
            "params": params,
            "id": int(time.time() * 1000),
        }

        try:
            msg = json.dumps(payload)
            if self.use_backend == "aiohttp":
                await self._ws.send_str(msg)
            else:
                await self._ws.send(msg)
            self.logger.info(f"📡 已发送订阅请求: {params} (ID: {payload['id']})")
        except Exception as e:
            self.logger.error(f"❌ 发送订阅失败: {e}")

    async def _handle_message(self, message: str) -> None:
        """
        处理 WebSocket 原始消息
        - 解析 JSON
        - 提取数据 (bookTicker 或 24hTicker)
        - 构造 TickerData 对象
        - 调用基类 _emit 广播
        """
        try:
            data = json.loads(message)
            
            # 忽略订阅响应 {"result": null, "id": 123}
            if "result" in data and data["result"] is None:
                return
                
            # 处理 24hrTicker / 24hTicker (现货/合约 24小时统计)
            # 🧩 注意：
            #   - 现货 Binance 事件名 = "24hrTicker"
            #   - 合约 Binance 可能推 "24hTicker" (少一个 r) 或 "24hrTicker"，两者都接受
            if "e" in data and data["e"] in ("24hrTicker", "24hTicker"):
                symbol_raw = data["s"].upper()
                target_symbol = self.symbol_map.get(symbol_raw)
                if not target_symbol:
                    return
                
                ticker = TickerData(
                    symbol=target_symbol,
                    timestamp=datetime.now(),
                    exchange=self.name,
                    last=Decimal(str(data["c"])),   # 最新价
                    open=Decimal(str(data["o"])),   # 开盘价
                    high=Decimal(str(data["h"])),   # 最高价
                    low=Decimal(str(data["l"])),    # 最低价
                    change=Decimal(str(data["p"])), # 涨跌额
                    percentage=Decimal(str(data["P"])), # 涨跌幅 %
                    volume=Decimal(str(data["v"])), # 成交量
                    quote_volume=Decimal(str(data["q"])), # 成交额
                    raw_data=data
                )
                await self._emit(asdict(ticker))
                return

            # 处理 bookTicker (无事件名，特征字段: b, a, s)
            if "b" in data and "a" in data and "s" in data:
                symbol_raw = data["s"].upper()
                target_symbol = self.symbol_map.get(symbol_raw)
                if not target_symbol:
                    return
                
                ticker = TickerData(
                    symbol=target_symbol,
                    timestamp=datetime.now(),
                    exchange=self.name,
                    bid=Decimal(str(data["b"])),
                    ask=Decimal(str(data["a"])),
                    bid_size=Decimal(str(data["B"])),
                    ask_size=Decimal(str(data["A"])),
                    # bookTicker 没有 last/change 等字段，只能提供盘口
                    raw_data=data
                )
                await self._emit(asdict(ticker))
                return
                
        except Exception as e:
            self.logger.error(f"消息处理错误: {e}")

    def _normalize_symbol(self, symbol: str) -> str:
        """
        已弃用：请使用 BinanceBase.normalize_symbol
        保留此方法仅为了兼容旧代码，直接代理到父类方法
        """
        return self.normalize_symbol(symbol)
