"""
核心数据模型与枚举定义模块

本模块定义了交易所适配器层通用的数据结构和枚举类型。
为保持轻量级，仅保留当前业务（行情、深度、账户、交易）所需的核心模型。

📌 主要包含:
    1. 🏷️ 枚举定义: OrderSide, OrderType, OrderStatus, PositionSide, MarginMode
    2. 📦 数据模型: TickerData, OrderBookData, BalanceData, PositionData, OrderData
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional, Any
from decimal import Decimal


# ==============================================================================
# 枚举定义 (Enumerations)
# ==============================================================================

class OrderSide(Enum):
    """
    🧭 订单方向枚举
    """
    BUY = "buy"                      # 🟢 买入
    SELL = "sell"                    # 🔴 卖出


class OrderType(Enum):
    """
    🏷️ 订单类型枚举
    """
    MARKET = "market"                # ⚡ 市价单 (按当前市场价格立即成交)
    LIMIT = "limit"                  # 🎯 限价单 (指定价格成交)


class OrderStatus(Enum):
    """
    🔄 订单状态枚举
    """
    PENDING = "pending"              # ⏳ 待处理 (已提交但未确认，或触发中)
    OPEN = "open"                    # 🟢 挂单中 (部分成交也属于 OPEN)
    FILLED = "filled"                # ✅ 完全成交 (所有数量均已成交)
    CANCELED = "canceled"            # 🚫 已撤销 (用户主动撤单)
    REJECTED = "rejected"            # ❌ 已拒绝 (交易所拒绝，如余额不足)
    EXPIRED = "expired"              # ⏰ 已过期 (FOK/IOC 等未成交部分)
    UNKNOWN = "unknown"              # ❓ 未知状态 (解析失败或暂无数据)


class PositionSide(Enum):
    """
    📈 持仓方向枚举
    """
    LONG = "long"                    # 🟢 多头
    SHORT = "short"                  # 🔴 空头
    BOTH = "both"                    # 🔄 双向持仓


class MarginMode(Enum):
    """
    🛡️ 保证金模式枚举
    """
    CROSS = "cross"                  # 🌐 全仓模式 (所有仓位共享保证金)
    ISOLATED = "isolated"            # 🔒 逐仓模式 (独立保证金，风险隔离)


# ==============================================================================
# 数据模型定义 (Data Models)
# ==============================================================================

@dataclass
class TickerData:
    """
    🎫 行情数据模型 (Ticker)
    包含最新成交价、买一卖一、24小时涨跌幅等信息。
    """
    symbol: str                      # 💱 交易对符号 (如 BTCUSDT, ETH/USD)
    timestamp: datetime              # 🕒 数据产生的时间戳 (本地或交易所时间)
    exchange: Optional[str] = None   # 🏦 交易所标识 (如 binance, okx)

    # === 基础价格信息 ===
    bid: Optional[Decimal] = None           # 🟢 最佳买一价 (Best Bid Price)
    ask: Optional[Decimal] = None           # 🔴 最佳卖一价 (Best Ask Price)
    bid_size: Optional[Decimal] = None      # 📦 最佳买一数量 (Best Bid Quantity)
    ask_size: Optional[Decimal] = None      # 📦 最佳卖一数量 (Best Ask Quantity)
    last: Optional[Decimal] = None          # 📊 最新成交价 (Last Traded Price)
    open: Optional[Decimal] = None          # 🌅 开盘价 (24h Rolling)
    high: Optional[Decimal] = None          # ⬆️ 最高价 (24h Rolling)
    low: Optional[Decimal] = None           # ⬇️ 最低价 (24h Rolling)
    close: Optional[Decimal] = None         # 🏁 收盘价 (通常等于 last)
    
    # === 成交量信息 ===
    volume: Optional[Decimal] = None        # 🧱 成交量 (Base Asset, 如 BTC)
    quote_volume: Optional[Decimal] = None  # 💵 成交额 (Quote Asset, 如 USDT)
    trades_count: Optional[int] = None      # 🔢 成交笔数 (24h)

    # === 价格变化信息 ===
    change: Optional[Decimal] = None        # 📉 价格变化额 (24h Change)
    percentage: Optional[Decimal] = None    # 📊 涨跌幅百分比 (24h Percentage)

    # === 原始数据 ===
    raw_data: Dict[str, Any] = field(default_factory=dict) # 📦 交易所返回的原始数据包

    def __post_init__(self):
        """⚙️ 自动将数值字段转换为 Decimal 类型，保证精度"""
        decimal_fields = [
            'bid', 'ask', 'bid_size', 'ask_size', 'last', 'open', 'high', 'low', 'close',
            'volume', 'quote_volume', 'change', 'percentage'
        ]
        for field_name in decimal_fields:
            value = getattr(self, field_name)
            if value is not None and isinstance(value, (int, float, str)):
                try:
                    setattr(self, field_name, Decimal(str(value)))
                except (ValueError, TypeError):
                    setattr(self, field_name, None)


@dataclass
class OrderBookData:
    """
    🌊 订单簿数据模型 (Depth/OrderBook)
    包含买卖盘的深度快照。
    
    📌 设计说明: 
    深度数据通常包含大量层级，为每一层创建对象会消耗大量内存和CPU。
    因此 bids/asks 使用 List[tuple] 结构更轻量、高效。
    """
    symbol: str                      # 💱 交易对符号
    bids: List[tuple[Decimal, Decimal]] # 🟢 买单队列 [(price, size), ...]，按价格降序排列
    asks: List[tuple[Decimal, Decimal]] # 🔴 卖单队列 [(price, size), ...]，按价格升序排列
    timestamp: datetime              # 🕒 数据快照时间戳
    nonce: Optional[int] = None      # 🔢 更新ID/版本号 (用于增量同步校验)
    raw_data: Dict[str, Any] = field(default_factory=dict) # 📦 原始数据

    @property
    def best_bid(self) -> Optional[tuple[Decimal, Decimal]]:
        """🟢 获取最佳买一价 (price, size)"""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[tuple[Decimal, Decimal]]:
        """🔴 获取最佳卖一价 (price, size)"""
        return self.asks[0] if self.asks else None


@dataclass
class BalanceData:
    """
    💰 账户余额数据模型 (Balance)
    包含单个币种的可用和冻结资金。
    """
    currency: str                    # 💵 币种符号 (如 USDT, BTC)
    free: Decimal                    # ✅ 可用余额 (Available)
    used: Decimal                    # 🔒 冻结/占用余额 (Locked/Frozen，通常因挂单或持仓)
    total: Decimal                   # 🔢 总余额 (Total = Free + Used)
    timestamp: datetime              # 🕒 数据更新时间
    raw_data: Dict[str, Any] = field(default_factory=dict) # 📦 原始数据

    def __post_init__(self):
        """⚙️ 自动类型转换"""
        if isinstance(self.free, (int, float, str)):
            self.free = Decimal(str(self.free))
        if isinstance(self.used, (int, float, str)):
            self.used = Decimal(str(self.used))
        if isinstance(self.total, (int, float, str)):
            self.total = Decimal(str(self.total))


@dataclass
class PositionData:
    """
    ⚠️ 合约持仓数据模型 (Position)
    包含合约账户的持仓详情。
    """
    symbol: str                      # 💱 交易对符号 (如 BTCUSDT)
    side: PositionSide               # 📈 持仓方向 (LONG/SHORT/BOTH)
    size: Decimal                    # 📏 持仓数量 (绝对值，不含方向符号)
    entry_price: Decimal             # 🎯 平均开仓价格 (Average Entry Price)
    unrealized_pnl: Decimal          # 💰 未实现盈亏 (Unrealized PnL)
    margin: Decimal                  # 🛡️ 持仓保证金 (Initial Margin)
    timestamp: datetime              # 🕒 数据更新时间
    leverage: int = 1                # ⚙️ 杠杆倍数
    margin_mode: MarginMode = MarginMode.CROSS  # 🛡️ 保证金模式 (全仓/逐仓)
    mark_price: Optional[Decimal] = None        # 🏷️ 当前标记价格 (用于计算盈亏和强平)
    liquidation_price: Optional[Decimal] = None # ☠️ 强平价格 (Estimated Liquidation Price)
    raw_data: Dict[str, Any] = field(default_factory=dict) # 📦 原始数据

    def __post_init__(self):
        """⚙️ 自动类型转换"""
        decimal_fields = ['size', 'entry_price', 'unrealized_pnl', 'margin', 'mark_price', 'liquidation_price']
        for field_name in decimal_fields:
            value = getattr(self, field_name)
            if value is not None and isinstance(value, (int, float, str)):
                setattr(self, field_name, Decimal(str(value)))


@dataclass
class OrderData:
    """
    📋 订单数据模型 (Order)
    包含委托单的详细状态。
    """
    id: str                          # 🆔 订单ID (交易所生成的唯一ID)
    symbol: str                      # 💱 交易对符号
    side: OrderSide                  # 🧭 买卖方向 (BUY/SELL)
    type: OrderType                  # 🏷️ 订单类型 (LIMIT/MARKET)
    amount: Decimal                  # 📏 委托数量 (Original Quantity)
    price: Optional[Decimal]         # 💰 委托价格 (市价单可能为None)
    filled: Decimal                  # ✅ 已成交数量 (Executed Quantity)
    remaining: Decimal               # ⏳ 剩余未成交数量 (Remaining Quantity)
    status: OrderStatus              # 🔄 订单状态 (OPEN/FILLED/CANCELED...)
    timestamp: datetime              # 🕒 订单创建时间
    client_id: Optional[str] = None  # 🏷️ 客户端自定义ID (Client Order ID)
    cost: Optional[Decimal] = None   # 💵 成交总金额 (Cumulative Quote Quantity)
    average: Optional[Decimal] = None # 📊 成交均价 (Average Fill Price)
    raw_data: Dict[str, Any] = field(default_factory=dict) # 📦 原始数据

    def __post_init__(self):
        """⚙️ 自动类型转换"""
        if isinstance(self.amount, (int, float, str)):
            self.amount = Decimal(str(self.amount))
        if self.price is not None and isinstance(self.price, (int, float, str)):
            self.price = Decimal(str(self.price))
        if isinstance(self.filled, (int, float, str)):
            self.filled = Decimal(str(self.filled))
        if isinstance(self.remaining, (int, float, str)):
            self.remaining = Decimal(str(self.remaining))
