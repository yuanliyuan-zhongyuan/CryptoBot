"""
MockExchange - 模拟交易所核心

职责：
- 模拟真实交易所的行为（连接、订阅、数据推送）
- 生成随机行情数据（基于随机漫步），用于本地开发和策略验证
- 提供统一的 subscribe 接口，供上层（Coordinator）接收数据

工作原理：
- 每个 Symbol 启动一个独立的 asyncio 任务 (_stream)
- 每隔 0.5 秒生成一个新的 bid/ask 价格
- 通过回调函数 (callback) 将数据推送给订阅者

注意：
- 这是一个"假"交易所，不做真实网络请求
- 价格是随机生成的，仅用于测试策略逻辑连通性
"""

import asyncio
import random
from typing import Dict, List, Callable

from .exchange_adapter import ExchangeAdapter


class MockExchange(ExchangeAdapter):
    def __init__(self, name: str, symbols: List[str]):
        super().__init__(name, symbols)

    async def start(self):
        self.running = True
        for s in self.symbols:
            self.tasks.append(asyncio.create_task(self._stream(s)))

    async def stop(self):
        self.running = False
        for t in self.tasks:
            t.cancel()
        self.tasks = []

    async def _stream(self, symbol: str):
        """内部数据流：模拟生成随机行情"""
        # 📊 设定基准价格（简单硬编码，仅作演示）
        base = {"BTC-USDC-PERP": 92000.0, "ETH-USDC-PERP": 3100.0}.get(symbol, 1000.0)
        
        while self.running:
            # 🎲 模拟价格波动（随机漫步）
            # - bid: 在基准价基础上微调
            # - ask: 在 bid 基础上加上随机点差
            bid = base * (1 + random.uniform(-0.001, 0.001))
            ask = bid * (1 + random.uniform(0.0001, 0.001))
            
            # 📦 封装数据包
            data = {"symbol": symbol, "bid": bid, "ask": ask, "exchange": self.name}
            
            # 📢 推送给所有订阅者
            for cb in self.subscribers.get(symbol, []):
                cb(data)
                
            # ⏱️ 模拟网络延迟 / 推送频率 (0.5s)
            await asyncio.sleep(0.5)
