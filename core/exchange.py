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


class MockExchange:
    def __init__(self, name: str, symbols: List[str]):
        # 🆔 交易所基本信息
        self.name = name
        self.symbols = symbols
        # ⚙️ 运行状态控制
        self.running = False
        self.tasks: List[asyncio.Task] = []
        # 📡 订阅管理：Symbol -> 回调函数列表
        self.subscribers: Dict[str, List[Callable]] = {}

    async def start(self):
        """启动交易所：为每个交易对创建模拟行情推送任务"""
        self.running = True
        # 1️⃣ 遍历所有交易对，启动独立的数据流任务
        for s in self.symbols:
            self.tasks.append(asyncio.create_task(self._stream(s)))
        # print(f"🚀 [{self.name}] 已启动，监控: {self.symbols}")

    async def stop(self):
        """停止交易所：取消所有后台任务"""
        self.running = False
        # 2️⃣ 优雅关闭所有行情任务
        for t in self.tasks:
            t.cancel()
        self.tasks = []
        # print(f"🛑 [{self.name}] 已停止")

    def subscribe(self, symbol: str, cb: Callable):
        """订阅接口：注册回调函数接收行情数据"""
        # 📝 简单的观察者模式：当有新行情时调用 cb(data)
        self.subscribers.setdefault(symbol, []).append(cb)

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

