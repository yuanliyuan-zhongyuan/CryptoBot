"""
Core 适配层包

用于放置针对不同交易所或数据源的适配器，实现统一接口。
"""

from .exchange_adapter import ExchangeAdapter
from .mockexchange_adapter import MockExchange
from .binance_adapter import BinanceAdapter
from .websocket_manager import WebSocketManager

__all__ = ["ExchangeAdapter", "MockExchange", "BinanceAdapter", "WebSocketManager"]
