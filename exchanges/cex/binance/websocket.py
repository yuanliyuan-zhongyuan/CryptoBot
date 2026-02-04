import asyncio
import json
import ssl
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
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
    Binance 专用 WebSocket 客户端
    
    继承体系：
    - WebSocketManager: 提供连接管理、回调分发等通用 WebSocket 能力
    - BinanceBase: 提供 Binance 特有的配置解析、符号转换等基础能力
    
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
        
        if websockets is None:
            raise ImportError("缺少 websockets 库，无法连接 Binance WebSocket，请先安装依赖")
            
        self.symbols = symbols or []
        # 注意：self.config 已经在 BinanceBase.__init__ 中设置
        
        self._tasks: List[asyncio.Task] = []
        self._ws = None
        self._running = False
        
        # 覆盖 BinanceBase 的 ws_url (因为这里需要动态测速选择)
        self.ws_url: Optional[str] = None
        
        self.symbol_map: Dict[str, str] = {}
        for s in self.symbols:
            # 使用 BinanceBase 提供的通用方法
            norm = self.normalize_symbol(s)
            self.symbol_map[norm] = s

    async def connect(self) -> None:
        """
        连接 WebSocket 并启动主循环
        """
        if self._running:
            return
        self._running = True
        await self._select_best_ws_url()
        self.logger.info(f"🚀 [{self.name}] WebSocket 即将连接到 {self.ws_url}")
        self._tasks.append(asyncio.create_task(self._main_loop()))

    async def subscribe(self, channels: List[str], stream_type: str = "bookTicker") -> None:
        """
        订阅指定的频道 (channels 即 symbol 列表)
        
        :param channels: 交易对列表 (如 ['BTCUSDT', 'ETHUSDT'])
        :param stream_type: 数据流类型，默认 bookTicker，可选 ticker (24h统计)
        """
        # 记录当前的流类型，供 _send_subscribe 使用
        self._current_stream_type = stream_type
        
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
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        self.logger.info(f"🛑 [{self.name}] WebSocket 已停止")

    async def _select_best_ws_url(self) -> None:
        """
        根据配置自动选择延迟最低的 WebSocket 节点
        - 读取配置文件中的 URL 列表
        - 区分现货 (Spot) 与 U 本位合约 (USD-M Futures)
        - 区分主网 (Mainnet) 与测试网 (Testnet)
        - 对每个节点进行连接测速
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
            self.logger.error("未找到任何 Binance WebSocket 配置 URL，请检查 binance.yaml 中 api.ws_base_urls 等字段")
            return
        best_url = None
        min_latency = float("inf")
        self.logger.info(f"🔍 [{self.name}] 正在自动优选最佳 WebSocket 节点...")
        for base_url in urls:
            target = base_url
            if not target.endswith("/ws") and not target.endswith("/stream"):
                target += "/ws"
            try:
                start_t = time.monotonic()
                async with websockets.connect(target, close_timeout=1, open_timeout=2) as ws:
                    _ = ws
                    latency = (time.monotonic() - start_t) * 1000
                    self.logger.info(f"  - 节点 {base_url} 延迟: {latency:.2f}ms")
                    if latency < min_latency:
                        min_latency = latency
                        best_url = target
            except Exception as e:
                self.logger.warning(f"  - 节点 {base_url} 连接失败: {e}")
        if best_url:
            self.ws_url = best_url
            self.logger.info(f"✅ 选中最佳节点: {self.ws_url} (延迟 {min_latency:.2f}ms)")
        else:
            self.logger.error("⚠️ 所有节点测试失败，未能选出可用 Binance WebSocket 节点")

    async def _main_loop(self) -> None:
        """
        WebSocket 主循环
        - 建立连接
        - 发送订阅
        - 持续接收消息
        - 异常自动重连
        """
        while self._running:
            try:
                if not self.ws_url:
                    self.logger.error("未配置有效的 Binance WebSocket URL，无法建立连接")
                    return
                async with websockets.connect(self.ws_url) as ws:
                    self._ws = ws
                    self.logger.info(f"✅ [{self.name}] WebSocket 连接成功")
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
        """
        if not self._ws or not self.symbols:
            return
        
        # 使用传入的流类型，或默认 bookTicker
        stream_type = getattr(self, "_current_stream_type", self.BinanceStreamType.BOOK_TICKER)
        
        params = [
            f"{self.normalize_symbol(s).lower()}@{stream_type}" for s in self.symbols
        ]
        payload = {
            "method": "SUBSCRIBE",
            "params": params,
            "id": int(time.time() * 1000),
        }
        await self._ws.send(json.dumps(payload))
        self.logger.info(f"📡 已发送订阅请求: {params} (ID: {payload['id']})")

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
                
            # 处理 24hrTicker (事件名: "24hrTicker")
            if "e" in data and data["e"] == "24hrTicker":
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
