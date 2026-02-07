"""
==============================================================================
📡  雷达扫描服务 (Scanner Service)
==============================================================================

🎯 模块作用
- 🚀 全市场扫描: 定期轮询交易所 REST API，获取所有交易对的 24h 行情
- 🧹 智能过滤: 剔除稳定币互换、低流动性僵尸币、风控黑名单币种
- 📊 排序优选: 按涨跌幅、成交量等指标打分，选出 Top N 热门标的
- 🔄 动态发现: 将发现的新机会推送给 SubscriptionManager，实现自动订阅

🔌 使用场景
- 作为"全域雷达"，弥补 Monitor 定点监控的盲区
- 与 SubscriptionManager 联动，实现「发现 ➜ 订阅 ➜ 追踪」的自动化闭环
- 适合发现突发热点、异动币种

� 输入 / �📤 输出
- 输入: Binance REST API (24hr Ticker)
- 输出: List[ScanResult] (标准化扫描结果列表)

🧭 运行流程 (Scanner Mode)
1) 定时器触发 (如每 60s)
2) 调用 API 拉取 2000+ 币种行情
3) 应用 Filter 规则 (计价币、黑名单、成交额阈值)
4) 计算 Score 并排序 (Top 10)
5) 更新 last_results 供 UI 展示或下游消费

🗂️ 配置速查 (binance_scanner.yaml)
- scan.interval: 扫描间隔 (秒)
- scan.limit: 返回结果数量 (Top N)
- markets.spot/futures: 市场开关与最小成交额门槛 (min_volume)
- filters.excluded_coins: 排除的币种 (如 USDC, BUSD)
==============================================================================
"""

import asyncio
import logging
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
from decimal import Decimal

from ...exchanges.cex.binance.rest import BinanceRest

logger = logging.getLogger("Core.Scanner")

@dataclass
class ScanResult:
    """
    📦 单次扫描结果项 (Value Object)
    
    用于封装单个币种的扫描结果，包含价格、涨跌幅、成交量等关键指标。
    提供 __str__ 方法以便于日志打印。
    
    🔑 字段说明
    - symbol: 交易对名称 (e.g. BTCUSDT)
    - price: 当前价格
    - change_24h: 24小时涨跌幅 (%)
    - volume_24h: 24小时成交额 (注意是 Quote Volume，单位通常是 USDT)
    - score: 综合评分 (目前主要基于涨跌幅绝对值，用于排序)
    """
    symbol: str
    price: Decimal
    change_24h: Decimal      # 24小时涨跌幅 (%)
    volume_24h: Decimal      # 24小时成交额 (USDT)
    high_24h: Decimal
    low_24h: Decimal
    score: float = 0.0       # 综合评分 (用于排序)

    def __str__(self):
        emoji = "🚀" if self.change_24h >= 0 else "📉"
        return f"{emoji} {self.symbol:<12} | 价: {self.price:>8} | 幅: {self.change_24h:>6.2f}% | 量: {self.volume_24h/10000:>8.0f}万"

class ScannerService:
    """
    🧠 雷达扫描服务 (Service Layer)
    - 负责执行具体的扫描逻辑：获取数据 -> 过滤 -> 排序
    - 纯粹的数据发现层，不涉及具体的交易执行
    
    核心方法:
    - scan_spot(): 扫描现货市场
    - scan_futures(): 扫描合约市场
    - update_config(): 热更新配置
    """
    
    def __init__(self, client: BinanceRest, config: Dict = None):
        """
        🚀 初始化
        :param client: Binance REST API 客户端 (用于拉取全量行情)
        :param config: 扫描配置字典
        """
        self.client = client
        self.config = config or {}
        self.last_results: List[ScanResult] = []
        
        self._parse_config()

    def update_config(self, config: Dict):
        """
        🔄 热更新配置
        - 允许在运行时调整过滤规则、成交额门槛等
        - 由外部 (如 run_scanner.py) 定期读取配置文件并调用
        """
        self.config = config
        self._parse_config()
        logger.info("✅ Scanner 配置已动态更新")

    def _parse_config(self):
        """
        ⚙️ 解析配置到本地属性
        - 将复杂的嵌套字典配置解析为扁平的本地属性，提高后续读取效率
        - 处理默认值回退逻辑
        """
        # 兼容旧配置 (直接在 root) 和新配置 (nested in markets/filters)
        
        # 1. 过滤配置
        filters_conf = self.config.get("filters", {})
        default_excluded = ["USDC", "USDT", "BUSD", "DAI", "TUSD", "FDUSD"]
        # 优先使用 filters.excluded_coins, 其次是 root.excluded_coins, 最后是默认值
        self.excluded_coins = set(filters_conf.get("excluded_coins") or self.config.get("excluded_coins", default_excluded))
        
        # 优先使用 filters.quote_assets, 默认 ["USDT"]
        self.quote_assets = set(filters_conf.get("quote_assets", ["USDT"]))

        # 2. 市场配置 (Spot)
        spot_conf = self.config.get("markets", {}).get("spot", {})
        # 优先使用 markets.spot.min_volume, 其次是 root.min_volume, 最后是 1000万
        self.spot_min_volume = Decimal(str(spot_conf.get("min_volume") or self.config.get("min_volume", "10000000")))

        # 3. 市场配置 (Futures)
        futures_conf = self.config.get("markets", {}).get("futures", {})
        # 优先使用 markets.futures.min_volume, 其次是 root.min_volume * 5 (默认合约量大), 最后是 5000万
        self.futures_min_volume = Decimal(str(futures_conf.get("min_volume") or self.config.get("min_volume", "50000000")))

        
    async def scan_spot(self, limit: int = 10) -> List[ScanResult]:
        """
        🛰️ 扫描 现货市场 (Spot)
        
        :param limit: 返回结果数量 (Top N)
        :return: 经过过滤和排序的 ScanResult 列表
        
        流程:
        1. client.get_ticker_24hr() -> 获取全量数据
        2. Filter: 计价币 (Quote Asset) 检查
        3. Filter: 基础币 (Base Asset) 黑名单检查
        4. Filter: 最小成交额 (Min Volume) 检查
        5. Sort: 按波动率 (Score) 降序排列
        """
        logger.info("📡 雷达启动: 正在扫描现货市场行情...")
        
        # 1. 获取 24hr Ticker 数据 (Spot)
        try:
            tickers = await self.client.get_ticker_24hr()
        except Exception as e:
            logger.error(f"❌ 扫描失败: API 请求错误 - {e}")
            return []
            
        if not tickers:
            logger.warning("⚠️ 扫描结果为空")
            return []
            
        logger.info(f"📥 收到 {len(tickers)} 个原始数据，开始筛选...")
        
        results = []
        
        for t in tickers:
            symbol = t.get('symbol', '')
            
            # 1. 过滤: 计价货币 (Quote Asset)
            # 假设所有计价货币都在末尾 (如 BTCUSDT -> USDT)
            # 更严谨的做法是遍历 self.quote_assets 检查 endswith
            is_valid_quote = False
            for quote in self.quote_assets:
                if symbol.endswith(quote):
                    is_valid_quote = True
                    break
            if not is_valid_quote:
                continue
                
            # 2. 过滤: 基础货币 (Base Asset)
            # 简单去除 Quote Asset 得到 Base Asset (不完美但够用)
            # 仅处理 USDT 结尾的情况
            base_asset = symbol
            for quote in self.quote_assets:
                if symbol.endswith(quote):
                    base_asset = symbol[:-len(quote)]
                    break
            
            if base_asset in self.excluded_coins:
                continue
                
            try:
                price = Decimal(str(t.get('lastPrice', 0)))
                change = Decimal(str(t.get('priceChangePercent', 0)))
                volume = Decimal(str(t.get('quoteVolume', 0))) # 使用成交额 (Quote Volume)
                high = Decimal(str(t.get('highPrice', 0)))
                low = Decimal(str(t.get('lowPrice', 0)))
                
                # 3. 过滤: 最小成交额
                if volume < self.spot_min_volume:
                    continue
                    
                results.append(ScanResult(
                    symbol=symbol,
                    price=price,
                    change_24h=change,
                    volume_24h=volume,
                    high_24h=high,
                    low_24h=low,
                    score=float(abs(change)) # 简单策略: 按波动幅度打分
                ))
                
            except Exception:
                continue
                
        # 排序: 按分数 (波动幅度) 降序
        results.sort(key=lambda x: x.score, reverse=True)
        
        # 截取 Top N
        top_results = results[:limit]
        self.last_results = top_results
        
        logger.info(f"✅ 现货扫描完成: 筛选出 {len(results)} 个有效标的，返回 Top {limit}")
        return top_results

    async def scan_futures(self, limit: int = 10) -> List[ScanResult]:
        """
        🛰️ 扫描 U本位合约市场 (Futures)
        
        :param limit: 返回结果数量 (Top N)
        :return: 经过过滤和排序的 ScanResult 列表
        
        逻辑与 scan_spot 类似，但使用合约 API 和独立的成交额门槛。
        """
        logger.info("📡 雷达启动: 正在扫描全市场行情...")
        
        # 1. 获取 24hr Ticker 数据 (REST API)
        try:
            tickers = await self.client.get_futures_ticker_24hr()
        except Exception as e:
            logger.error(f"❌ 扫描失败: API 请求错误 - {e}")
            return []
            
        if not tickers:
            logger.warning("⚠️ 扫描结果为空")
            return []
            
        logger.info(f"📥 收到 {len(tickers)} 个原始数据，开始筛选...")
        
        results = []
        
        for t in tickers:
            symbol = t.get('symbol', '')
            
            # 1. 过滤: 计价货币
            is_valid_quote = False
            for quote in self.quote_assets:
                if symbol.endswith(quote):
                    is_valid_quote = True
                    break
            if not is_valid_quote:
                continue
                
            # 2. 过滤: 基础货币
            base_asset = symbol
            for quote in self.quote_assets:
                if symbol.endswith(quote):
                    base_asset = symbol[:-len(quote)]
                    break
            
            if base_asset in self.excluded_coins:
                continue
                
            try:
                price = Decimal(str(t.get('lastPrice', 0)))
                change = Decimal(str(t.get('priceChangePercent', 0)))
                volume = Decimal(str(t.get('quoteVolume', 0))) # 使用成交额
                high = Decimal(str(t.get('highPrice', 0)))
                low = Decimal(str(t.get('lowPrice', 0)))
                
                # 3. 过滤: 最小成交额 (使用合约配置)
                if volume < self.futures_min_volume:
                    continue
                    
                results.append(ScanResult(
                    symbol=symbol,
                    price=price,
                    change_24h=change,
                    volume_24h=volume,
                    high_24h=high,
                    low_24h=low,
                    score=float(abs(change)) 
                ))
                
            except Exception:
                continue
                
        # 排序
        results.sort(key=lambda x: x.score, reverse=True)
        
        # 截取
        top_results = results[:limit]
        self.last_results = top_results
        
        logger.info(f"✅ 扫描完成: 筛选出 {len(results)} 个有效标的，返回 Top {limit}")
        return top_results
