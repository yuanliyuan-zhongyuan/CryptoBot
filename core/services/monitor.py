"""
==============================================================================
🛠️  价格监控报警服务 (Simplified for CryptoTrade)
==============================================================================

🎯 模块作用
- 接收交易所实时行情 (Ticker) 数据
- 维护每个币种的统计信息：当前价、24h 涨跌、最高/最低、短期波动率
- 根据配置执行两类报警：⚡ 波动率报警、🎯 目标价报警
- 提供简易的 🔊 声音提示 与 🧾 历史记录

🔌 使用场景
- 与 WebSocket 适配器联动，形成「数据 ➜ 处理 ➜ 展示/报警」闭环
- 适合作为入门级业务服务，后续可逐步拆分为更细的服务模块

📥 输入 / 📤 输出
- 输入：TickerData (或等价 Dict)，包含 last/high/low/percentage 等字段
- 输出：logger 警告日志、蜂鸣提示、alert_history 最近 10 条记录

🧭 运行流程 (简化版)
1) WebSocket 收到行情，回调 on_ticker_update
2) 更新币种统计信息 (SymbolStatistics)
3) 检查是否触发：⚡ 波动率 或 🎯 目标价
4) 若触发：记录历史、输出日志、可选声音提示

🗂️ 配置速查 (alert_config)
- alert.sound: 是否播放声音 (bool)
- alert.cooldown: 同一币种报警冷却秒数 (int)
- symbols: 币种列表
  - symbol: "BTC/USDT" 等
  - enabled: 是否启用
  - volatility: { enabled, window, threshold }  # 波动率报警参数
  - price_target: { enabled, upper, lower }     # 目标价报警参数
==============================================================================
"""

import asyncio
import logging
import sys
import time
from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Deque, Union

from cryptotrade.core.adapters.models import TickerData


class SymbolStatistics:
    """
    📦 单个代币统计数据 (Runtime State)
    - 负责在内存中保存某个币种的运行时状态
    - 由 PriceMonitorService 管理与更新

    🔑 字段说明
    - current_price: 最新成交价
    - change_percent_24h: 24h 涨跌幅 (%)，来源 ticker.percentage
    - high_24h / low_24h: 24h 最高/最低价
    - price_history: 最近价格序列，用于计算短期波动率
    - total_alerts / last_alert_time: 报警次数与上次报警时间 (冷却控制)
    - last_update_time: 最近一次更新的时间戳
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.current_price: Decimal = Decimal("0")
        self.price_24h_ago: Decimal = Decimal("0")
        self.change_percent_24h: float = 0.0
        self.high_24h: Decimal = Decimal("0")
        self.low_24h: Decimal = Decimal("0")
        
        # 价格历史 (用于计算短期波动)
        # 存储 (timestamp, price) 元组
        self.price_history: Deque[tuple[float, Decimal]] = deque(maxlen=3600) # 1小时历史
        
        # 报警统计
        self.total_alerts: int = 0
        self.last_alert_time: float = 0
        self.last_update_time: Optional[datetime] = None

    def update(self, ticker: TickerData):
        """
        🔄 更新统计数据
        - 将最新行情写入到统计对象
        - 维护用于波动率计算的价格历史 (timestamp, price)
        """
        if ticker.last:
            self.current_price = ticker.last
            self.price_history.append((time.time(), ticker.last))
        
        if ticker.percentage:
            self.change_percent_24h = float(ticker.percentage)

        if ticker.high:
            self.high_24h = ticker.high
        if ticker.low:
            self.low_24h = ticker.low
            
        self.last_update_time = datetime.now()

    def get_window_change(self, window_seconds: int) -> Optional[float]:
        """
        📐 计算指定时间窗口内的价格变化百分比
        - 原理：取窗口起点价格与当前价格，计算 (curr - start) / start * 100
        - 若历史不足或起始价为 0，则返回 None 或 0.0，以保证安全
        """
        if len(self.price_history) < 2:
            return None
            
        now_ts = time.time()
        start_price = None
        
        # 从后往前找，找到第一个早于 window_seconds 的点
        # 或者最接近 window_seconds 的点
        target_ts = now_ts - window_seconds
        
        # 简单遍历 (因为 maxlen 不大，性能可接受)
        # 寻找最接近 target_ts 的点
        best_point = None
        
        for ts, price in self.price_history:
            if ts >= target_ts:
                best_point = price
                break # 找到了窗口内的最早点
        
        if best_point is None:
            # 历史数据不足以覆盖窗口，取最早的一个点
            best_point = self.price_history[0][1]
            
        start_price = best_point
        
        if start_price == 0:
            return 0.0
            
        return float((self.current_price - start_price) / start_price * 100)


class PriceMonitorService:
    """
    🧠 价格监控服务 (Service Layer)
    - 作为业务服务层入口，承接 Ticker 数据并执行报警逻辑
    - 与 UI (run_monitor.py) 配合，提供表格展示所需统计信息

    📜 配置结构 (alert_config) 约定
    - alert.sound: 是否播放声音
    - alert.cooldown: 同一币种两次报警的最小间隔秒数
    - symbols: 币种配置列表，每项包含：
      - symbol: "BTC/USDT" 等
      - enabled: 是否启用
      - volatility: { enabled, window, threshold }  # ⚡ 波动率报警参数
      - price_target: { enabled, upper, lower }     # 🎯 目标价报警参数
    """
    
    def __init__(self, alert_config: Dict):
        """
        🚀 初始化
        :param alert_config: 报警配置字典 (见类注释中的结构约定)
        动作：
        - 建立日志器
        - 保存配置
        - 为每个启用的币种创建统计对象
        """
        self.logger = logging.getLogger("PriceMonitor")
        self.config = alert_config
        self.statistics: Dict[str, SymbolStatistics] = {}
        self.alert_history: List[str] = []
        
        # 初始化统计对象
        for s_conf in self.config.get("symbols", []):
            if s_conf.get("enabled", True):
                self.statistics[s_conf["symbol"]] = SymbolStatistics(s_conf["symbol"])

    def update_config(self, new_config: Dict):
        """
        🔄 热更新配置
        - 允许在运行时动态调整报警阈值、冷却时间等
        - 注意：不会动态增删 SymbolStatistics 对象 (仅更新现有参数)
        """
        self.config = new_config
        self.logger.info("配置已热更新")

    async def on_ticker_update(self, ticker: Union[TickerData, Dict]):
        """
        📩 处理 Ticker 更新
        - 入口：由 WebSocket 适配器回调触发
        - 兼容：既支持 TickerData，也支持 Dict (自动转为 TickerData)
        - 输出：更新统计后，进行报警检查
        """
        # 🔁 兼容字典格式 (解决 WebSocketManager 回调必须是 Dict 的问题)
        if isinstance(ticker, dict):
            ticker = TickerData(**ticker)

        symbol = ticker.symbol
        if symbol not in self.statistics:
            return
            
        stats = self.statistics[symbol]
        stats.update(ticker)
        
        await self._check_alerts(symbol, stats)

    async def _check_alerts(self, symbol: str, stats: SymbolStatistics):
        """
        🛎️ 检查报警条件
        - 包含两类检查：⚡ 波动率报警 与 🎯 目标价报警
        - 冷却控制：若距离上次报警不足 cooldown 秒，则不触发
        """
        s_conf = self._get_symbol_config(symbol)
        if not s_conf:
            return
            
        now = time.time()
        cooldown = self.config.get("alert", {}).get("cooldown", 60)
        
        # 冷却检查
        if now - stats.last_alert_time < cooldown:
            return

        triggered = False
        message = ""
        
        # 1. 波动率检查
        vol_conf = s_conf.get("volatility", {})
        if vol_conf.get("enabled", True):
            window = vol_conf.get("window", 300)
            threshold = vol_conf.get("threshold", 1.0)
            
            change = stats.get_window_change(window)
            if change is not None and abs(change) >= threshold:
                direction = "📈 暴涨" if change > 0 else "📉 暴跌"
                message = f"{direction} {symbol}: {window}秒内波动 {change:+.2f}% (阈值 {threshold}%)"
                triggered = True

        # 2. 价格目标检查
        if not triggered:
            price_conf = s_conf.get("price_target", {})
            if price_conf.get("enabled", True):
                upper = price_conf.get("upper", 0)
                lower = price_conf.get("lower", 0)
                curr = float(stats.current_price)
                
                if upper > 0 and curr >= upper:
                    message = f"🚀 突破上限 {symbol}: 当前 {curr} >= {upper}"
                    triggered = True
                elif lower > 0 and curr <= lower:
                    message = f"🔻 跌破下限 {symbol}: 当前 {curr} <= {lower}"
                    triggered = True

        if triggered:
            await self._trigger_alert(symbol, message)
            stats.last_alert_time = now
            stats.total_alerts += 1

    async def _trigger_alert(self, symbol: str, message: str):
        """
        📣 触发报警动作
        - 记录报警历史 (最多保留 10 条)
        - 输出日志警告
        - 可选声音提示
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {message}"
        self.alert_history.append(full_msg)
        if len(self.alert_history) > 10:
            self.alert_history.pop(0)
            
        self.logger.warning(full_msg)
        
        # 声音报警
        if self.config.get("alert", {}).get("sound", True):
            self._play_sound()

    def _play_sound(self):
        """
        🔊 播放声音 (非阻塞尝试)
        - Windows: 使用 winsound.Beep 简易蜂鸣
        - 其他系统: 使用 '\\a' 响铃字符
        - 若播放失败，静默忽略
        """
        try:
            if sys.platform == "win32":
                import winsound
                # 异步播放不太容易，这里简单用 Beep (会短暂阻塞，但可接受)
                winsound.Beep(1000, 500)
            else:
                print("\a")
        except:
            pass

    def _get_symbol_config(self, symbol: str) -> Optional[Dict]:
        """
        🗂️ 获取某个币种的配置块
        - 遍历 alert_config.symbols，匹配 symbol 字段
        """
        for s in self.config.get("symbols", []):
            if s["symbol"] == symbol:
                return s
        return None
