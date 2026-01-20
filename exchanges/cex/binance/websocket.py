import asyncio
import json
import ssl
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from cryptotrade.core.adapters.websocket_manager import WebSocketManager

try:
    import websockets
except ImportError:
    websockets = None


class BinanceWebSocket(WebSocketManager):
    """
    Binance 专用 WebSocket 客户端

    作用：
    - 根据配置中现货 / U 本位开关，自动选择合适的 WebSocket 节点
    - 建立与 Binance 的长连接，发送 SUBSCRIBE 订阅 bookTicker 流
    - 将 Binance 原始行情转换为统一字典，并通过 WebSocketManager._emit 向上层广播

    数据流：
        Binance WebSocket ➜ BinanceWebSocket._handle_message ➜ _emit(formatted)
        ➜ BinanceAdapter._on_ticker ➜ TradingCoordinator.on_ticker
    """

    def __init__(self, name: str, symbols: List[str], config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name=name)
        if websockets is None:
            raise ImportError("缺少 websockets 库，无法连接 Binance WebSocket，请先安装依赖")
        self.symbols = symbols or []
        self.config = config or {}
        self._tasks: List[asyncio.Task] = []
        self._ws = None
        self._running = False
        self.ws_url: Optional[str] = None
        self.symbol_map: Dict[str, str] = {}
        for s in self.symbols:
            norm = self._normalize_symbol(s)
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

    async def subscribe(self, channels: List[str]) -> None:
        """
        订阅指定的频道 (channels 即 symbol 列表)
        """
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
        构造并发送 Binance 订阅请求 (SUBSCRIBE)
        使用 bookTicker 频道订阅最优买卖价
        """
        if not self.symbols or not self._ws:
            return
        streams = []
        for s in self.symbols:
            norm = self._normalize_symbol(s)
            streams.append(f"{norm}@bookTicker")
        payload = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": 1,
        }
        await self._ws.send(json.dumps(payload))
        self.logger.info(f"📡 [{self.name}] 已发送订阅请求: {streams}")

    async def _handle_message(self, message: str) -> None:
        """
        处理 WebSocket 原始消息
        - 解析 JSON
        - 提取 bookTicker 数据 (bid/ask)
        - 格式化为统一字典
        - 调用基类 _emit 广播
        """
        try:
            data = json.loads(message)
            if "result" in data and data["result"] is None:
                return
            if "b" in data and "a" in data and "s" in data:
                symbol_raw = data["s"].lower()
                target_symbol = self.symbol_map.get(symbol_raw)
                if not target_symbol:
                    return
                formatted = {
                    "symbol": target_symbol,
                    "bid": float(data["b"]),
                    "ask": float(data["a"]),
                    "exchange": self.name,
                    "timestamp": datetime.now().timestamp(),
                }
                await self._emit(formatted)
        except Exception as e:
            self.logger.error(f"消息处理错误: {e}")

    def _normalize_symbol(self, s: str) -> str:
        """
        标准化交易对符号
        例如: "BTC/USDT" -> "btcusdt"
        兼容: "BTC-USDT", "BTC_USDT", "BTCUSDT"
        """
        t = s.strip().upper()
        t = t.replace("/", "").replace("_", "").replace("-", "")
        t = s.upper().replace("/", "").replace("_", "").replace("-", "")
        if "PERP" in t:
            t = t.replace("PERP", "")
        if ":" in t:
            t = t.split(":")[0]
        return t.lower()
