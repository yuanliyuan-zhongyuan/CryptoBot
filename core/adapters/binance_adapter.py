"""
Binance 交易所适配器（学习项目版）

作用：
- 作为 CryptoTrade 学习项目中 Binance 的“桥接层”
- 内部使用 BinanceWebSocket 获取实盘行情
- 对外暴露与 MockExchange 相同的 subscribe 接口，方便 TradingCoordinator 无感切换

数据流：
    Binance WebSocket ➜ BinanceWebSocket（专用客户端）
    ➜ BinanceAdapter._on_ticker ➜ TradingCoordinator.on_ticker
"""

import logging
from typing import Dict, List, Callable

from .exchange_adapter import ExchangeAdapter
from cryptotrade.exchanges.cex.binance.websocket import BinanceWebSocket

logger = logging.getLogger(__name__)

class BinanceAdapter(ExchangeAdapter):
    """
    Binance 实盘行情适配器
    
    作用：
    - 作为 TradingCoordinator 与 Binance 底层 WebSocket 的中间层
    - 管理 WebSocket 生命周期 (Start/Stop)
    - 维护订阅关系表 (Symbol -> Callbacks)
    
    数据流：
    BinanceWebSocket (emit) ➜ BinanceAdapter._on_ticker ➜ TradingCoordinator (callback)
    """

    def __init__(self, name: str = "binance", symbols: List[str] = None, config: Dict = None):
        """
        初始化适配器
        - 设置交易所名称
        - 加载初始交易对列表
        - 保存配置信息
        """
        super().__init__(name, symbols or [])
        self.config = config or {}
        self.ws_client: BinanceWebSocket | None = None
            
    async def start(self):
        """
        启动实盘行情
        - 初始化 BinanceWebSocket 实例
        - 注册内部数据转发回调 (_on_ticker)
        - 建立 WebSocket 连接
        """
        self.running = True
        logger.info(f"🚀 [{self.name}] 正在启动 Binance 实时行情")
        self.ws_client = BinanceWebSocket(self.name, self.symbols, self.config)
        self.ws_client.add_callback(self._on_ticker)
        await self.ws_client.connect()

    async def stop(self):
        """
        停止实盘行情
        - 断开 WebSocket 连接
        - 清理后台任务
        """
        self.running = False
        logger.info(f"🛑 [{self.name}] 正在停止 Binance 实时行情")
        if self.ws_client:
            await self.ws_client.disconnect()
        for t in self.tasks:
            t.cancel()
        self.tasks = []

    def subscribe(self, symbol: str, cb: Callable):
        """
        订阅指定交易对的行情
        - 将回调函数注册到 subscribers 字典中
        - 当收到该 symbol 的行情时，触发所有注册的回调
        """
        self.subscribers.setdefault(symbol, []).append(cb)

    def _on_ticker(self, data: Dict):
        """
        处理来自底层 WebSocket 的行情数据
        - 解析数据中的 symbol
        - 查找订阅了该 symbol 的所有回调函数
        - 依次执行回调，将数据推送给上层
        """
        symbol = data.get("symbol")
        if not symbol:
            return
        for cb in self.subscribers.get(symbol, []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"回调执行错误: {e}")
