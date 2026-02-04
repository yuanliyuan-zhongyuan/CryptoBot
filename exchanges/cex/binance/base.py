from enum import Enum
from typing import Dict, List, Optional
from cryptotrade.core.adapters.models import OrderStatus, OrderType

"""
📘 Binance Base Module
======================

此模块定义了 Binance 交易所的基础常量、配置和通用逻辑。
作为 REST 和 WebSocket 客户端的基类，提供统一的配置管理和工具方法。

📌 主要包含:
    1. 🔗 API 端点定义 (BinanceRestEndpoint)
    2. 🏷️ 市场类型枚举 (BinanceMarketType)
    3. 🔄 状态与类型映射 (ORDER_STATUS_MAPPING, ORDER_TYPE_MAPPING)
    4. 📡 WebSocket 数据流类型 (BinanceStreamType)
    5. 🛠️ 通用工具方法 (normalize_symbol)
"""

class BinanceRestEndpoint(str, Enum):
    """
    🔗 Binance REST API Endpoints
    定义现货 (Spot) 和 合约 (Futures) 的 API 路径
    """
    
    # 🌐 Public Data (公共数据)
    EXCHANGE_INFO = "/api/v3/exchangeInfo"
    TICKER_BOOK = "/api/v3/ticker/bookTicker"
    DEPTH = "/api/v3/depth"
    KLINES = "/api/v3/klines"
    SERVER_TIME = "/api/v3/time"

    # 👤 Account & Trade (现货账户与交易)
    ACCOUNT = "/api/v3/account"
    ORDER = "/api/v3/order"
    OPEN_ORDERS = "/api/v3/openOrders"

    # 📈 Futures Account & Trade (合约账户与交易)
    FUTURES_ACCOUNT = "/fapi/v2/account"        # 💰 U本位合约账户信息
    FUTURES_ORDER = "/fapi/v1/order"            # 📝 合约下单/撤单
    FUTURES_OPEN_ORDERS = "/fapi/v1/openOrders" # 📋 合约普通挂单
    FUTURES_OPEN_ALGO_ORDERS = "/fapi/v1/openAlgoOrders" # 🤖 合约算法挂单
    POSITION_RISK = "/fapi/v2/positionRisk"     # ⚠️ 持仓风险/当前持仓


class BinanceMarketType(Enum):
    """
    🏷️ Binance Market Type
    区分现货和合约市场
    """
    SPOT = "spot"          # 现货市场
    FUTURES = "future"     # 合约市场 (U本位)
    # DELIVERY = "delivery"  # 币本位 (暂未实现)


class BinanceBase:
    """
    🏗️ Binance Base Class
    
    Binance 适配器的基类，负责：
    1. ⚙️ 加载 API 配置 (Key, Secret, URL)
    2. 🔄 定义核心枚举映射 (状态、类型)
    3. 🛠️ 提供通用数据处理方法
    """

    # 🔄 订单状态映射: Binance -> Standard
    ORDER_STATUS_MAPPING = {
        'NEW': OrderStatus.OPEN,
        'PARTIALLY_FILLED': OrderStatus.OPEN,  # ✨ 部分成交仍然视为 OPEN
        'FILLED': OrderStatus.FILLED,
        'CANCELED': OrderStatus.CANCELED,
        'REJECTED': OrderStatus.REJECTED,
        'EXPIRED': OrderStatus.EXPIRED
    }

    # 🔄 订单类型映射: Standard -> Binance
    ORDER_TYPE_MAPPING = {
        OrderType.MARKET: 'MARKET',
        OrderType.LIMIT: 'LIMIT'
    }

    # 📡 WebSocket 订阅类型常量 
    # 因为需要监控，所以添加了一些流
    class BinanceStreamType(str, Enum):
        """WebSocket 数据流类型"""
        BOOK_TICKER = "bookTicker"  # 📊 最优买卖价 (原 TICKER)
        TICKER = "bookTicker"       # 兼容旧代码，指向 bookTicker
        TICKER_24H = "ticker"       # 📈 24小时统计 (含涨跌幅)
        TRADE = "trade"             # 🤝 实时成交
        DEPTH = "depth"        # 🌊 深度信息
        KLINE = "kline"        # 🕯️ K线数据
        USER_DATA = "userData" # 👤 用户数据流 (订单、账户更新)

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化 Binance 基础配置
        
        :param config: 配置字典，包含 api 和 authentication 部分
        """
        self.config: Dict = config or {}
        api_conf = self.config.get("api", {})
        
        # 🌐 REST URL 配置
        self.base_url: str = api_conf.get("base_url", "https://api.binance.com")
        self.futures_base_url: str = api_conf.get("futures_base_url", "https://fapi.binance.com")

        # 📡 WebSocket URL 配置
        self.ws_base_urls: List[str] = api_conf.get("ws_base_urls", [
            "wss://stream.binance.com:9443", 
            "wss://stream.binance.com:443"
        ])
        self.futures_ws_base_urls: List[str] = api_conf.get("futures_ws_base_urls", [
            "wss://fstream.binance.com",
            "wss://fstream.binance.com/ws"
        ])

        # 🔑 认证配置
        auth_conf = self.config.get("authentication", {})
        self.api_key: str = auth_conf.get("api_key", "")
        self.api_secret: str = auth_conf.get("api_secret", "")

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """
        🛠️ 符号标准化
        将通用格式转换为 Binance 格式
        
        Example:
            "BTC/USDT" -> "BTCUSDT"
            "ETH_USDT" -> "ETHUSDT"
        """
        return symbol.replace("/", "").replace("_", "").upper()
