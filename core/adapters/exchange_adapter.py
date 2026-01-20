import asyncio
from typing import Dict, List, Callable


class ExchangeAdapter:
    def __init__(self, name: str, symbols: List[str]):
        self.name = name
        self.symbols = symbols
        self.running = False
        self.tasks: List[asyncio.Task] = []
        self.subscribers: Dict[str, List[Callable]] = {}

    async def start(self):
        self.running = True

    async def stop(self):
        self.running = False
        for t in self.tasks:
            t.cancel()
        self.tasks = []

    def subscribe(self, symbol: str, cb: Callable):
        self.subscribers.setdefault(symbol, []).append(cb)

