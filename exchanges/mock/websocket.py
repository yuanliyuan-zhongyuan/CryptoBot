import asyncio
import random
from typing import List
from cryptotrade.core.adapters.websocket_manager import WebSocketManager

class MockWebSocket(WebSocketManager):
    """
    Mock 交易所 WebSocket 实现
    
    用于本地开发和测试，生成随机行情数据
    """
    
    def __init__(self, symbols: List[str] = None):
        super().__init__(name="Mock")
        self.symbols = symbols or []
        self._tasks: List[asyncio.Task] = []
        
    async def connect(self):
        self._running = True
        self.logger.info("✅ Mock WebSocket 已启动 (虚拟连接)")
        # 启动模拟数据流
        for s in self.symbols:
            self._tasks.append(asyncio.create_task(self._stream(s)))

    async def subscribe(self, channels: List[str]):
        self.logger.info(f"📡 Mock 订阅: {channels}")
        # 在 Mock 中，我们可能在初始化时就决定了要模拟哪些 symbol
        # 或者在这里动态添加新的模拟任务
        for s in channels:
            if s not in self.symbols:
                self.symbols.append(s)
                if self._running:
                    self._tasks.append(asyncio.create_task(self._stream(s)))
        
    async def disconnect(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        self.logger.info("❌ Mock WebSocket 已停止")

    async def _stream(self, symbol: str):
        """内部方法：模拟生成随机行情并广播"""
        base = {"BTC-USDC-PERP": 92000.0, "ETH-USDC-PERP": 3100.0}.get(symbol, 1000.0)
        
        while self._running:
            # 模拟价格波动
            bid = base * (1 + random.uniform(-0.001, 0.001))
            ask = bid * (1 + random.uniform(0.0001, 0.001))
            
            data = {
                "exchange": self.name,
                "symbol": symbol,
                "bid": bid,
                "ask": ask
            }
            
            # 使用基类的广播方法
            await self._emit(data)
            await asyncio.sleep(0.5)
