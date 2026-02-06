"""
📡 雷达扫描服务 (Scanner Service)
==============================

此模块实现了全市场扫描功能 (雷达模式)。
它负责定期轮询交易所 REST API，筛选出符合条件的交易对。

📌 主要功能:
    1. 🔍 全市场扫描: 获取所有交易对的 24小时行情
    2. 🧹 过滤筛选: 剔除稳定币、低流动性币种
    3. 📊 排序排名: 按涨跌幅、成交量等指标排序
    4. 📤 结果输出: 生成标准化扫描结果，供 SubscriptionManager 使用

这一层是纯粹的数据发现层，不涉及具体交易策略。
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
    """单次扫描结果项"""
    symbol: str
    price: Decimal
    change_24h: Decimal      # 24小时涨跌幅 (%)
    volume_24h: Decimal      # 24小时成交量 (USDT)
    high_24h: Decimal
    low_24h: Decimal
    score: float = 0.0       # 综合评分 (用于排序)

    def __str__(self):
        emoji = "🚀" if self.change_24h >= 0 else "📉"
        return f"{emoji} {self.symbol:<12} | 价: {self.price:>8} | 幅: {self.change_24h:>6.2f}% | 量: {self.volume_24h/10000:>8.0f}万"

class ScannerService:
    """
    雷达扫描服务
    """
    
    def __init__(self, client: BinanceRest, config: Dict = None):
        self.client = client
        self.config = config or {}
        self.last_results: List[ScanResult] = []
        
        self._parse_config()

    def update_config(self, config: Dict):
        """
        🔄 动态更新配置
        """
        self.config = config
        self._parse_config()
        logger.info("✅ Scanner 配置已动态更新")

    def _parse_config(self):
        """解析配置到本地属性"""
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
        :return: 扫描结果列表
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
        🛰️ 扫描 U本位合约市场
        
        :param limit: 返回结果数量 (Top N)
        :return: 扫描结果列表
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
