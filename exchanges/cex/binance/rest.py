"""
📘 Binance REST API Client
==========================

此模块实现了 Binance 交易所的 REST API 客户端。
基于 aiohttp 实现异步请求，提供市场数据、账户信息、订单管理等功能。

📌 主要功能:
    1. 🔐 签名认证 (HMAC-SHA256)
    2. 🌐 公共数据接口 (K线, 深度, Ticker)
    3. 👤 私有账户接口 (余额, 持仓, 挂单)
    4. 📈 混合支持现货 (Spot) 与合约 (Futures)

注意：
- 保持了与大项目一致的方法签名。
- 内部自动处理了现货/合约的 API URL 切换。
"""

import asyncio
import aiohttp
import hmac
import hashlib
import time
import urllib.parse
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from decimal import Decimal

from cryptotrade.exchanges.cex.binance.base import BinanceBase, BinanceRestEndpoint
from cryptotrade.core.adapters.models import (
    TickerData, BalanceData, OrderData, OrderStatus, OrderSide, OrderType,
    OrderBookData, PositionData, PositionSide, MarginMode
)

logger = logging.getLogger("Binance.REST")


class BinanceRest(BinanceBase):
    """
    🏗️ Binance REST Client Implementation
    
    Binance REST API 客户端实现类。
    """
    
    def __init__(self, config: Dict = None):
        """
        初始化 REST 客户端
        
        :param config: 配置字典 (包含 api_key, secret, urls 等)
        """
        super().__init__(config)
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limit_orders = 1200
        self.rate_limit_requests = 2400
        self.max_retries = 3
        self.retry_delay = 1.0

        if self.api_key:
            logger.info(f"✅ [Binance REST] API Key 已配置")
        else:
            logger.info("⚠️ [Binance REST] 未配置 API Key，仅可访问公共接口")

    async def initialize(self) -> bool:
        """
        🚀 初始化 HTTP 会话
        创建 aiohttp session 并执行健康检查。
        
        :return: 初始化是否成功
        """
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            # 测试连接
            await self.health_check()
            logger.info("✅ [Binance REST] 初始化成功")
            return True
        except Exception as e:
            logger.error(f"❌ [Binance REST] 初始化失败: {e}")
            return False

    async def health_check(self):
        """
        💓 API 健康检查
        请求服务器时间接口，确保网络连接正常。
        """
        try:
            # 访问服务器时间接口作为健康检查
            # 这是一个轻量级的公共接口
            await self._request("GET", BinanceRestEndpoint.SERVER_TIME)
        except Exception as e:
            raise ConnectionError(f"API 连接检查失败: {e}")

    async def close(self):
        """
        🛑 关闭连接
        释放 HTTP 会话资源。
        """
        if self.session:
            await self.session.close()
            self.session = None

    async def _request(self, method: str, endpoint: str, params: Dict = None, signed: bool = False) -> Any:
        """
        📡 通用请求方法
        统一处理签名、重试、错误处理。
        
        :param method: HTTP 方法 (GET, POST, DELETE...)
        :param endpoint: API 端点 (如 /api/v3/ticker)
        :param params: 请求参数
        :param signed: 是否需要签名 (私有接口)
        :return: 响应 JSON 数据 或 None
        """
        if not self.session:
            await self.initialize()

        url = f"{self.base_url}{endpoint}"
        params = params or {}
        headers = {}

        if signed:
            if not self.api_key or not self.api_secret:
                raise ValueError("需要 API Key 和 Secret 才能访问私有接口")
            
            headers["X-MBX-APIKEY"] = self.api_key
            params["timestamp"] = int(time.time() * 1000)
            
            # 生成签名
            query_string = urllib.parse.urlencode(params)
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                query_string.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            
            if method == "GET" or method == "DELETE":
                url = f"{url}?{query_string}&signature={signature}"
                params = None
            else:
                # POST 参数处理
                params["signature"] = signature

        for attempt in range(self.max_retries):
            try:
                async with self.session.request(method, url, params=params, data=params if method=="POST" else None, headers=headers) as response:
                    resp_json = await response.json()
                    
                    if response.status >= 400:
                        logger.warning(f"API调用失败 [{response.status}]: {resp_json}")
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(self.retry_delay * (attempt + 1))
                            continue
                        return None
                    
                    return resp_json
            except Exception as e:
                logger.error(f"网络请求异常: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    return None
        return None

    # ==================== 📊 市场数据接口 (Market Data) ====================

    async def get_exchange_info(self) -> Dict:
        """
        ℹ️ 获取交易所信息
        包含所有交易对的规则、精度等信息。
        """
        return await self._request("GET", BinanceRestEndpoint.EXCHANGE_INFO)

    async def get_futures_exchange_info(self) -> Dict:
        """
        ℹ️ 获取合约交易所信息 (U本位)
        包含所有合约交易对的规则、精度等信息。
        """
        original_base_url = self.base_url
        self.base_url = self.futures_base_url
        try:
            return await self._request("GET", BinanceRestEndpoint.FUTURES_EXCHANGE_INFO)
        finally:
            self.base_url = original_base_url

    async def get_ticker(self, symbol: str) -> Optional[TickerData]:
        """
        🎫 获取单个行情 (Ticker)
        
        :param symbol: 交易对符号 (如 BTCUSDT)
        :return: TickerData 对象或 None
        """
        fmt_symbol = self.normalize_symbol(symbol)
        data = await self._request(
            "GET",
            BinanceRestEndpoint.TICKER_BOOK,
            {"symbol": fmt_symbol},
        )
        if not data:
            return None
            
        return TickerData(
            symbol=symbol,
            timestamp=datetime.now(),
            bid=Decimal(str(data.get("bidPrice"))),
            ask=Decimal(str(data.get("askPrice"))),
            bid_size=Decimal(str(data.get("bidQty"))),
            ask_size=Decimal(str(data.get("askQty"))),
            raw_data=data
        )

    async def get_ticker_24hr(self, symbol: str = None) -> Any:
        """
        📈 获取 24小时价格变动统计 (Spot)
        
        :param symbol: 交易对符号 (可选，不传则返回所有)
        :return: 字典或字典列表
        """
        params = {}
        if symbol:
            params["symbol"] = self.normalize_symbol(symbol)
            
        return await self._request("GET", BinanceRestEndpoint.TICKER_24HR, params)

    async def get_futures_ticker_24hr(self, symbol: str = None) -> Any:
        """
        📈 获取合约 24小时价格变动统计 (Futures)
        
        :param symbol: 交易对符号 (可选，不传则返回所有)
        :return: 字典或字典列表
        """
        original_base_url = self.base_url
        self.base_url = self.futures_base_url
        try:
            params = {}
            if symbol:
                params["symbol"] = self.normalize_symbol(symbol)
                
            return await self._request("GET", BinanceRestEndpoint.FUTURES_TICKER_24HR, params)
        finally:
            self.base_url = original_base_url

    async def get_tickers(self) -> List[Dict]:
        """
        📑 获取所有行情数据
        返回原始字典列表，暂不转换对象以节省开销。
        """
        return await self._request("GET", BinanceRestEndpoint.TICKER_BOOK)

    async def get_orderbook(self, symbol: str, limit: int = 100) -> Optional[OrderBookData]:
        """
        🌊 获取订单簿深度 (OrderBook)
        
        :param symbol: 交易对符号
        :param limit: 深度层级数量 (默认 100)
        :return: OrderBookData 对象或 None
        """
        fmt_symbol = self.normalize_symbol(symbol)
        data = await self._request(
            "GET",
            BinanceRestEndpoint.DEPTH,
            {"symbol": fmt_symbol, "limit": limit},
        )
        if not data:
            return None

        # 转换 bids (直接使用 tuple 更轻量)
        bids = [
            (Decimal(str(p)), Decimal(str(s)))
            for p, s in data.get("bids", [])
        ]
        # 转换 asks
        asks = [
            (Decimal(str(p)), Decimal(str(s)))
            for p, s in data.get("asks", [])
        ]

        return OrderBookData(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(),
            nonce=data.get("lastUpdateId"),
            raw_data=data
        )

    # ==================== 👤 账户接口 (Account & Trade) ====================

    async def get_balances(self) -> List[BalanceData]:
        """
        💰 获取账户余额
        
        功能：
        1. 自动聚合 现货 (Spot) 和 合约 (Futures) 账户余额。
        2. 自动过滤余额为 0 的币种。
        
        :return: BalanceData 对象列表
        """
        balances = []
        
        # 1. 获取现货余额
        try:
            spot_data = await self._request(
                "GET",
                BinanceRestEndpoint.ACCOUNT,
                signed=True,
            )
            if spot_data:
                for b in spot_data.get("balances", []):
                    free = Decimal(str(b["free"]))
                    used = Decimal(str(b["locked"]))
                    if free > 0 or used > 0:
                        balances.append(BalanceData(
                            currency=f"{b['asset']} (Spot)", # 标记为现货
                            free=free,
                            used=used,
                            total=free + used,
                            timestamp=datetime.now(),
                            raw_data=b
                        ))
        except Exception as e:
            logger.warning(f"获取现货余额失败: {e}")

        # 2. 获取合约余额 (U本位)
        try:
            # 切换到合约 base_url
            original_base_url = self.base_url
            self.base_url = self.futures_base_url # 切换到 fapi
            
            futures_data = await self._request(
                "GET",
                BinanceRestEndpoint.FUTURES_ACCOUNT,
                signed=True,
            )
            
            self.base_url = original_base_url # 还原 base_url
            
            if futures_data:
                # 合约账户返回结构不同，是 assets 数组
                for b in futures_data.get("assets", []):
                    free = Decimal(str(b["availableBalance"])) # 可用余额
                    # 合约中 locked 概念比较复杂，这里简化为 钱包余额 - 可用余额
                    wallet_balance = Decimal(str(b["walletBalance"]))
                    used = wallet_balance - free
                    
                    if wallet_balance > 0:
                        balances.append(BalanceData(
                            currency=f"{b['asset']} (Futures)", # 标记为合约
                            free=free,
                            used=used,
                            total=wallet_balance,
                            timestamp=datetime.now(),
                            raw_data=b
                        ))
        except Exception as e:
             logger.warning(f"获取合约余额失败: {e}")
            
        return balances

    async def get_positions(self) -> List[PositionData]:
        """
        ⚠️ 获取合约持仓 (Position)
        
        功能：
        1. 仅针对合约账户有效。
        2. 双重检查机制 (v2/positionRisk 和 v2/account)。
        3. 自动解析持仓方向、盈亏、杠杆等信息。
        
        :return: PositionData 对象列表
        """
        positions = []
        # 注意: 这里假设调用者已经切换了 base_url，或者当前实例就是合约实例
        # 但为了稳健，我们应该像 get_balances 一样临时切换
             
        original_base_url = self.base_url
        # 如果当前不是 fapi，且配置了 futures_base_url，则尝试切换
        if "fapi" not in self.base_url and self.futures_base_url:
             self.base_url = self.futures_base_url
        
        logger.info(f"DEBUG: 正在请求合约持仓 (URL: {self.base_url}{BinanceRestEndpoint.POSITION_RISK})")

        try:
            # 1. 尝试使用 v2/positionRisk 获取详细持仓信息
            data = await self._request(
                "GET",
                BinanceRestEndpoint.POSITION_RISK,
                signed=True,
            )
            if data:
                logger.info(f"DEBUG: v2/positionRisk 返回了 {len(data)} 条数据")
                for p in data:
                    amt_str = str(p.get("positionAmt", "0"))
                    amt = Decimal(amt_str)
                    symbol = p.get("symbol")
                    
                    # 详细调试：打印特定币种 (HYPEUSDT) 或所有非零持仓
                    if "HYPE" in symbol or amt != 0:
                         logger.info(f"DEBUG: 检查持仓 {symbol}: amt={amt_str} (Decimal={amt})")

                    if amt != 0:
                        logger.info(f"DEBUG: 发现持仓: {symbol} amt={amt}")
                        positions.append(PositionData(
                            symbol=symbol,
                            side=PositionSide.LONG if amt > 0 else PositionSide.SHORT, # 简化判断
                            size=abs(amt),
                            entry_price=Decimal(str(p.get("entryPrice", "0"))),
                            unrealized_pnl=Decimal(str(p.get("unRealizedProfit", "0"))),
                            margin=Decimal(str(p.get("positionInitialMargin", "0"))), # 初始保证金
                            timestamp=datetime.now(),
                            leverage=int(p.get("leverage", 1)),
                            margin_mode=MarginMode.CROSS if p.get("marginType") == "cross" else MarginMode.ISOLATED,
                            mark_price=Decimal(str(p.get("markPrice", "0"))),
                            liquidation_price=Decimal(str(p.get("liquidationPrice", "0"))),
                            raw_data=p
                        ))
            else:
                logger.info("DEBUG: v2/positionRisk 返回为空")

            # 2. 如果没查到持仓，尝试使用 v2/account (备选方案，用户建议)
            if not positions:
                logger.info("DEBUG: 尝试使用备选接口 v2/account 获取持仓...")
                account_data = await self._request(
                    "GET",
                    BinanceRestEndpoint.FUTURES_ACCOUNT,
                    signed=True,
                )
                if account_data and "positions" in account_data:
                    acc_positions = account_data.get("positions", [])
                    logger.info(f"DEBUG: v2/account 返回了 {len(acc_positions)} 条持仓数据")
                    for p in acc_positions:
                        amt_str = str(p.get("positionAmt", "0"))
                        amt = Decimal(amt_str)
                        symbol = p.get("symbol")
                        
                        if "HYPE" in symbol or amt != 0:
                             logger.info(f"DEBUG: (Account) 检查持仓 {symbol}: amt={amt_str}")

                        if amt != 0:
                            logger.info(f"DEBUG: (Account接口) 发现持仓: {symbol} amt={amt}")
                            positions.append(PositionData(
                                symbol=symbol,
                                side=PositionSide.LONG if amt > 0 else PositionSide.SHORT,
                                size=abs(amt),
                                entry_price=Decimal(str(p.get("entryPrice", "0"))),
                                unrealized_pnl=Decimal(str(p.get("unrealizedProfit", "0"))),
                                margin=Decimal(str(p.get("initialMargin", "0"))), # 注意字段名可能不同
                                timestamp=datetime.now(),
                                leverage=int(p.get("leverage", 1)) if "leverage" in p else 1, # Account接口可能不含杠杆
                                margin_mode=MarginMode.ISOLATED if p.get("isolated") else MarginMode.CROSS, # 字段不同
                                mark_price=Decimal("0"), # Account 接口不含标记价格
                                liquidation_price=Decimal("0"), # Account 接口不含强平价格
                                raw_data=p
                            ))
                else:
                    logger.info("DEBUG: v2/account 返回为空或无 positions 字段")
        except Exception as e:
            logger.warning(f"获取持仓失败: {e}")
        finally:
            self.base_url = original_base_url
            
        return positions

    async def get_futures_account_info(self) -> Dict:
        """
        🛠️ 获取合约账户详细信息 (Debug用途)
        """
        original_base_url = self.base_url
        if "fapi" not in self.base_url and self.futures_base_url:
             self.base_url = self.futures_base_url
        
        try:
            return await self._request(
                "GET",
                BinanceRestEndpoint.FUTURES_ACCOUNT,
                signed=True,
            )
        finally:
            self.base_url = original_base_url

    async def get_open_orders(self, symbol: str = None) -> List[OrderData]:
        """
        📋 获取当前挂单 (Open Orders)
        
        功能：
        1. 智能路由：自动分别查询 现货 (Spot) 和 合约 (Futures) 挂单。
        2. 全面覆盖：合约部分同时查询 普通挂单 (openOrders) 和 算法挂单 (openAlgoOrders)。
        3. 错误隔离：某一类查询失败不会影响其他结果。
        
        :param symbol: 交易对符号 (可选)
        :return: OrderData 对象列表
        """
        orders = []
        params = {}
        if symbol:
            params["symbol"] = self.normalize_symbol(symbol)

        # 保存原始 base_url 以便恢复
        original_base_url = self.base_url
        
        # 获取配置中的 URL (如果未在 config 中显式定义，使用默认值)
        # 注意：这里我们假设 self.base_url 初始就是现货 URL，或者我们从 config 重新获取
        spot_url = self.config.get("api", {}).get("base_url", "https://api.binance.com")
        futures_url = self.futures_base_url # __init__ 中已加载

        # -------------------------------------------------------
        # 1. 查询现货挂单
        # -------------------------------------------------------
        try:
            # 临时切换到现货 URL
            self.base_url = spot_url
            endpoint = BinanceRestEndpoint.OPEN_ORDERS
            
            # 只有当 URL 确实是现货 API 时才查询 (避免配置错误)
            if "api.binance.com" in self.base_url or "api" in self.base_url:
                data = await self._request(
                    "GET",
                    endpoint,
                    params,
                    signed=True,
                )
                if data:
                    orders.extend(self._parse_orders(data))
        except Exception as e:
            # 现货查询失败通常忽略 (可能是因为用户只做合约，或者 symbol 不存在于现货)
            # logger.warning(f"查询现货挂单失败: {e}")
            pass

        # -------------------------------------------------------
        # 2. 查询合约挂单 (普通单 + 算法单)
        # -------------------------------------------------------
        if futures_url:
            try:
                self.base_url = futures_url
                
                # 2.1 合约普通挂单
                try:
                    endpoint = BinanceRestEndpoint.FUTURES_OPEN_ORDERS
                    data = await self._request(
                        "GET",
                        endpoint,
                        params,
                        signed=True,
                    )
                    if data:
                        orders.extend(self._parse_orders(data))
                except Exception as e:
                    logger.warning(f"查询合约普通挂单失败: {e}")

                # 2.2 合约算法挂单 (止盈止损等)
                try:
                    # 优先使用枚举，兼容旧代码
                    if hasattr(BinanceRestEndpoint, 'FUTURES_OPEN_ALGO_ORDERS'):
                        endpoint = BinanceRestEndpoint.FUTURES_OPEN_ALGO_ORDERS
                    else:
                        endpoint = "/fapi/v1/openAlgoOrders"

                    data = await self._request(
                        "GET",
                        endpoint,
                        params,
                        signed=True,
                    )
                    if data:
                        orders.extend(self._parse_algo_orders(data))
                except Exception as e:
                    # 算法单查询失败可能是因为该 symbol 没有算法单功能，记录 debug 即可
                    # logger.debug(f"查询合约算法挂单失败: {e}")
                    pass

            finally:
                # 无论如何恢复原始 URL
                self.base_url = original_base_url
        
        return orders

    def _parse_orders(self, data: List[Dict]) -> List[OrderData]:
        """
        ⚙️ 解析普通订单列表
        将 API 返回的原始字典转换为标准 OrderData 对象。
        """
        orders = []
        for o in data:
            # 状态映射
            status_map = {
                "NEW": OrderStatus.OPEN,
                "PARTIALLY_FILLED": OrderStatus.OPEN,
                "FILLED": OrderStatus.FILLED,
                "CANCELED": OrderStatus.CANCELED,
                "PENDING_CANCEL": OrderStatus.PENDING,
                "REJECTED": OrderStatus.REJECTED,
                "EXPIRED": OrderStatus.EXPIRED,
            }
            
            orders.append(OrderData(
                id=str(o.get("orderId")),
                symbol=o.get("symbol"),
                side=OrderSide.BUY if o.get("side") == "BUY" else OrderSide.SELL,
                type=OrderType.LIMIT if o.get("type") == "LIMIT" else OrderType.MARKET, 
                amount=Decimal(str(o.get("origQty"))),
                price=Decimal(str(o.get("price"))),
                filled=Decimal(str(o.get("executedQty"))),
                remaining=Decimal(str(o.get("origQty"))) - Decimal(str(o.get("executedQty"))),
                status=status_map.get(o.get("status"), OrderStatus.UNKNOWN),
                timestamp=datetime.fromtimestamp(o.get("time") / 1000),
                client_id=o.get("clientOrderId"),
                raw_data=o
            ))
        return orders

    def _parse_algo_orders(self, data: List[Dict]) -> List[OrderData]:
        """
        🤖 解析合约算法订单列表
        处理特殊的算法单字段 (algoId, stopPrice 等)。
        """
        orders = []
        for o in data:
            # 状态映射 (算法单状态可能略有不同)
            # NEW, TRIGGERED, FILLED, ...
            status_str = o.get("algoStatus", o.get("status", "UNKNOWN"))
            status_map = {
                "NEW": OrderStatus.OPEN,
                "NOT_TRIGGERED": OrderStatus.OPEN, # 未触发也视为 Open
                "TRIGGERED": OrderStatus.OPEN,     # 已触发但未完全成交?
                "FILLED": OrderStatus.FILLED,
                "CANCELED": OrderStatus.CANCELED,
                "REJECTED": OrderStatus.REJECTED,
            }
            
            # 价格字段处理 (算法单可能有 stopPrice, triggerPrice 等)
            price = Decimal("0")
            if "price" in o and float(o["price"]) > 0:
                price = Decimal(str(o["price"]))
            elif "stopPrice" in o:
                price = Decimal(str(o["stopPrice"]))
            elif "triggerPrice" in o:
                price = Decimal(str(o["triggerPrice"]))

            qty = Decimal(str(o.get("quantity", o.get("origQty", "0"))))
            
            orders.append(OrderData(
                id=str(o.get("algoId", o.get("orderId"))), # 优先使用 algoId
                symbol=o.get("symbol"),
                side=OrderSide.BUY if o.get("side") == "BUY" else OrderSide.SELL,
                type=OrderType.LIMIT, # 暂时统一定义，虽然可能是 STOP_MARKET 等
                amount=qty,
                price=price,
                filled=Decimal(str(o.get("executedQty", "0"))),
                remaining=qty - Decimal(str(o.get("executedQty", "0"))),
                status=status_map.get(status_str, OrderStatus.UNKNOWN),
                timestamp=datetime.fromtimestamp(o.get("time", o.get("updateTime", 0)) / 1000),
                client_id=o.get("clientAlgoId"),
                raw_data=o
            ))
        return orders
