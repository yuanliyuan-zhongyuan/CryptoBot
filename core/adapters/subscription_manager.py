"""
📘 Subscription Manager
=======================

此模块实现了交易所订阅管理器，用于管理交易对的订阅状态。
支持预定义（硬编码）和动态（自动发现）两种订阅模式。

📌 主要功能:
    1. 🔄 两种订阅模式: PREDEFINED (配置文件), DYNAMIC (运行时发现)
    2. 📊 订阅状态管理: 添加/移除/统计
    3. 🔍 符号发现支持: 配合扫描器使用
    4. 🧩 最小依赖设计: 独立于具体交易所实现

🏗️ 架构说明:
    - SubscriptionManager: 核心管理类
    - SubscriptionMode: 模式枚举
    - DataType: 数据类型枚举 (Ticker, OrderBook, etc.)
"""

import time
import logging
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Set, Union
from dataclasses import dataclass, field

# 使用统一的日志记录器
logger = logging.getLogger("Core.SubscriptionManager")

class SubscriptionMode(Enum):
    """
    🔀 订阅模式枚举
    
    - PREDEFINED: 硬编码模式，使用配置文件中预定义的交易对
    - DYNAMIC: 动态模式，运行时自动发现或外部注入交易对
    """
    PREDEFINED = "predefined"
    DYNAMIC = "dynamic"

class DataType(Enum):
    """
    📦 数据类型枚举
    
    定义了系统支持的订阅数据类型。
    """
    TICKER = "ticker"          # 24小时行情推送
    ORDERBOOK = "orderbook"    # 深度信息
    TRADES = "trades"          # 最新成交
    KLINE = "kline"            # K线数据
    USER_DATA = "user_data"    # 用户私有数据 (账户/订单)

@dataclass
class SubscriptionInfo:
    """
    📝 订阅信息数据类
    
    记录单个订阅的详细信息。
    """
    symbol: str
    data_type: DataType
    callback: Optional[Callable] = None
    params: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

class SubscriptionManager:
    """
    🛡️ 订阅管理器
    
    负责维护交易所的订阅状态，支持批量管理和动态更新。
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化订阅管理器
        
        :param config: 交易所配置字典 (通常包含 subscription_mode 等字段)
        """
        self.config = config or {}
        
        # 内部状态
        self.subscriptions: Dict[str, SubscriptionInfo] = {}
        self.active_symbols: Set[str] = set()
        
        # 统计信息
        self.stats = {
            'total_subscriptions': 0,
            'active_subscriptions': 0,
            'failed_subscriptions': 0,
            'last_update': time.time()
        }
        
        # 动态发现缓存
        self._cached_symbols: List[str] = []
        self._last_discovery_time: float = 0
        
        # 解析配置
        self._parse_config()
        
        logger.info(f"✅ 订阅管理器初始化完成 (模式: {self.mode.value})")

    def _parse_config(self):
        """解析配置文件"""
        # 优先查找 'subscription' (新标准)，回退到 'subscription_mode' (旧兼容)
        subscription_config = self.config.get('subscription', self.config.get('subscription_mode', {}))
        
        # 订阅模式
        mode_str = subscription_config.get('mode', 'predefined')
        try:
            self.mode = SubscriptionMode(mode_str)
        except ValueError:
            logger.warning(f"⚠️ 未知订阅模式: {mode_str}, 降级为 predefined")
            self.mode = SubscriptionMode.PREDEFINED
        
        # 硬编码模式配置
        predefined_config = subscription_config.get('predefined', {})
        self.predefined_symbols = predefined_config.get('symbols', [])
        self.predefined_data_types = predefined_config.get('data_types', {})
        
        # 动态模式配置
        dynamic_config = subscription_config.get('dynamic', {})
        self.dynamic_data_types = dynamic_config.get('data_types', {})

    def get_subscription_symbols(self) -> List[str]:
        """
        📋 获取当前应订阅的交易对列表
        
        根据当前模式返回交易对列表。
        - PREDEFINED: 返回配置文件中的列表
        - DYNAMIC: 返回雷达扫描到的缓存列表
        """
        if self.mode == SubscriptionMode.PREDEFINED:
            return self.predefined_symbols.copy()
        else:
            return self._cached_symbols.copy()

    def update_dynamic_symbols(self, symbols: List[str]):
        """
        📡 动态更新订阅列表 (雷达模式专用)
        
        当 Scanner 发现新机会时调用此方法
        """
        if self.mode != SubscriptionMode.DYNAMIC:
            logger.warning("⚠️ 当前不是动态订阅模式，忽略更新请求")
            return
            
        old_set = set(self._cached_symbols)
        new_set = set(symbols)
        
        added = new_set - old_set
        removed = old_set - new_set
        
        self._cached_symbols = symbols
        self.stats['last_update'] = time.time()
        
        if added or removed:
            logger.info(f"🔄 订阅列表更新: +{len(added)} / -{len(removed)} (总计: {len(symbols)})")
            # 注意: 这里只更新了数据，具体的 WebSocket 订阅/退订动作
            # 需要由外部协调器 (Coordinator) 定期检查差异来执行

    def add_subscription(self, symbol: str, data_type: DataType, callback: Optional[Callable] = None, **kwargs):
        """
        ➕ 添加订阅记录
        
        :param symbol: 交易对符号 (e.g. BTCUSDT)
        :param data_type: 数据类型 (DataType.TICKER)
        :param callback: 回调函数
        """
        key = self._make_key(symbol, data_type)
        
        if key in self.subscriptions:
            logger.debug(f"ℹ️ 订阅已存在: {key}")
            return
            
        self.subscriptions[key] = SubscriptionInfo(
            symbol=symbol,
            data_type=data_type,
            callback=callback,
            params=kwargs
        )
        
        self.active_symbols.add(symbol)
        self.stats['total_subscriptions'] += 1
        self.stats['active_subscriptions'] += 1
        self.stats['last_update'] = time.time()
        
        logger.debug(f"✅ 添加订阅: {key}")

    def remove_subscription(self, symbol: str, data_type: DataType):
        """
        ➖ 移除订阅记录
        """
        key = self._make_key(symbol, data_type)
        
        if key in self.subscriptions:
            del self.subscriptions[key]
            self.stats['active_subscriptions'] -= 1
            self.stats['last_update'] = time.time()
            
            # 检查该符号是否还有其他订阅
            is_active = any(sub.symbol == symbol for sub in self.subscriptions.values())
            if not is_active:
                self.active_symbols.discard(symbol)
                
            logger.debug(f"🗑️ 移除订阅: {key}")

    def get_active_symbols(self) -> List[str]:
        """
        🔍 获取当前活跃的符号列表
        """
        return list(self.active_symbols)
        
    def get_stats(self) -> Dict[str, Any]:
        """
        📊 获取统计信息
        """
        return {
            'mode': self.mode.value,
            'total_symbols': len(self.active_symbols),
            'cached_symbols': len(self._cached_symbols),
            'subscriptions': self.stats
        }

    def _make_key(self, symbol: str, data_type: DataType) -> str:
        """生成唯一的订阅键"""
        return f"{symbol}_{data_type.value}"
