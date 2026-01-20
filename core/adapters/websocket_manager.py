from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, List
import asyncio
import logging


class WebSocketManager(ABC):
    """
    WebSocket 管理器基类

    作用：
    - 抽象出“连接 + 订阅 + 数据广播”的通用骨架
    - 为各交易所专用 WebSocket 提供统一的回调分发机制
    - 避免在 Adapter 里直接写低层 WebSocket 细节
    """

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"WS.{name}")
        self._callbacks: List[Callable[[Dict], Any]] = []
        self._running = False
        
    def add_callback(self, callback: Callable[[Dict], Any]):
        """注册数据回调函数"""
        self._callbacks.append(callback)
        
    async def _emit(self, data: Dict):
        """内部方法：向所有监听者广播数据"""
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

    @abstractmethod
    async def connect(self):
        """建立连接 (由子类实现具体逻辑)"""
        pass
        
    @abstractmethod
    async def subscribe(self, channels: List[str]):
        """订阅频道 (由子类实现具体逻辑)"""
        pass
        
    @abstractmethod
    async def disconnect(self):
        """断开连接 (由子类实现具体逻辑)"""
        pass
