"""
TradingCoordinator - CryptoTrade 协调层核心

职责：
- 作为「大脑」，串联配置加载 / 行情订阅 / 策略选择
- 管理多交易所 MockExchange，并统一存储最新行情快照
- 根据策略类型选择对应 Runner（网格 / 套利），并驱动其运行

数据流（简化版）：
    MockExchange  ➜  TradingCoordinator.on_ticker  ➜  latest 状态
       │                                           ➜  当前 Runner.on_ticker（预留）
       └─ 多个交易所并行推送

使用方式：
- 由 run.py 中创建并调用：
    coordinator = TradingCoordinator(...)
    await coordinator.start()
    await coordinator.run_cli(duration)
    await coordinator.stop()
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List
import yaml
from cryptotrade.core.adapters import MockExchange, BinanceAdapter


class TradingCoordinator:
    """
    TradingCoordinator - CryptoTrade 协调层核心

    职责：
    - 作为「大脑」，串联配置加载 / 行情订阅 / 策略选择
    - 管理多交易所 Adapter (Real/Mock)，并统一存储最新行情快照
    - 根据策略类型选择对应 Runner（网格 / 套利），并驱动其运行

    数据流（简化版）：
        Exchange Adapter  ➜  TradingCoordinator.on_ticker  ➜  latest 状态
           │                                                ➜  当前 Runner.on_ticker
           └─ 多个交易所并行推送

    使用方式：
    - 由 run.py 中创建并调用：
        coordinator = TradingCoordinator(...)
        await coordinator.start()
        await coordinator.run_cli(duration)
        await coordinator.stop()
    """

    def __init__(self, cex_dir: Path, dex_dir: Path, strategy_config_path: Path, risk_config_path: Path):
        """
        初始化协调器
        - 设置配置文件的路径
        - 初始化内部状态容器 (exchanges, latest, baseline)
        - 预设策略与风控配置为空字典，等待 load_configs 填充
        """
        # 📁 配置路径相关
        self.cex_dir = cex_dir
        self.dex_dir = dex_dir
        self.strategy_config_path = strategy_config_path
        self.risk_config_path = risk_config_path
        # 📄 配置内容（运行前通过 load_configs 填充）
        self.strategy_config: Dict[str, Any] = {}
        self.risk_config: Dict[str, Any] = {}
        # 🎯 当前策略类型（决定使用哪个 Runner）
        self.strategy_type = ""
        # 🌐 交易所与行情状态
        self.exchanges: Dict[str, MockExchange] = {}
        self.latest: Dict[str, Dict[str, Dict[str, float]]] = {}
        self.baseline: Dict[str, float] = {}
        self.best_pairs: Dict[str, Dict[str, str]] = {}
        self.primary_exchange = ""
        # 🏃 当前策略 Runner（GridRunner / ArbitrageRunner）
        self.runner = None
        # ▶️ 整体运行开关
        self.running = False
        self.print_tickers = False
        self._last_print_ts: Dict[str, float] = {}

    def load_configs(self):
        """
        加载策略与风控配置
        - 读取 yaml 配置文件
        - 解析策略类型 (strategy_type)
        - 设置系统运行模式 (print_tickers 等)
        """
        with open(self.strategy_config_path, "r", encoding="utf-8") as f:
            self.strategy_config = yaml.safe_load(f) or {}
        with open(self.risk_config_path, "r", encoding="utf-8") as f:
            self.risk_config = yaml.safe_load(f) or {}
        self.strategy_type = self.strategy_config.get("type", "arbitrage_segmented")
        self.print_tickers = bool(self.strategy_config.get("system_mode", {}).get("print_tickers", False))

    def get_symbols(self) -> List[str]:
        """
        从策略配置中解析出需要监控的交易对列表
        支持三种配置格式：
        1. 直接列表: symbols: ["BTC/USDT", ...]
        2. 字典键: symbol_configs: {"BTC/USDT": ...}
        3. 三角套利: triangles: [{legs: [...]}]
        """
        sc = self.strategy_config
        if sc.get("symbols"):
            return list(sc["symbols"])
        if sc.get("symbol_configs"):
            return list(sc.get("symbol_configs", {}).keys())
        if sc.get("triangles"):
            legset = set()
            for t in sc["triangles"]:
                for l in t.get("legs", []):
                    legset.add(l)
            return list(legset)
        return []

    def _get_exchanges(self) -> List[Dict[str, Any]]:
        """
        从 CEX/DEX 配置目录中解析出启用的交易所配置
        - 遍历目录下的 .yaml 文件
        - 兼容根节点包裹的配置结构
        - 过滤掉 enabled: false 的交易所
        """
        configs: List[Dict[str, Any]] = []
        for d in [self.cex_dir, self.dex_dir]:
            if not d.exists():
                continue
            for p in d.glob("*.yaml"):
                with open(p, "r", encoding="utf-8") as f:
                    raw_data = yaml.safe_load(f) or {}
                
                # 兼容带有根节点的配置结构 (如 binance.yaml 中的 binance: ...)
                if p.stem in raw_data and isinstance(raw_data[p.stem], dict):
                    data = raw_data[p.stem]
                else:
                    data = raw_data

                if not data.get("enabled", True):
                    continue
                if "name" not in data:
                    data["name"] = p.stem
                configs.append(data)
        return configs

    def grid_params(self, symbol: str) -> Dict[str, Any]:
        """
        合并默认配置与单币种配置，得到网格参数
        优先使用 symbol_configs 中的特定配置，缺失则回退到 default_config
        """
        default = self.strategy_config.get("default_config", {}).get("grid_config", {})
        sc = self.strategy_config.get("symbol_configs", {}).get(symbol, {})
        gc = sc.get("grid_config", {})
        return {
            "initial": gc.get("initial_spread_threshold", default.get("initial_spread_threshold", 0.02)),
            "step": gc.get("grid_step", default.get("grid_step", 0.01)),
            "max": gc.get("max_segments", default.get("max_segments", 5)),
        }

    def monitor_only(self) -> bool:
        """
        判断系统是否处于仅监控模式
        - True: 仅打印信号，不进行任何交易操作
        - False: 允许执行实际交易逻辑
        """
        return bool(self.strategy_config.get("system_mode", {}).get("monitor_only", True))

    def on_ticker(self, data: Any):
        """
        行情回调：处理接收到的 Ticker 数据
        - 支持 Dict (兼容旧代码/Mock) 和 TickerData 对象 (新架构)
        - 更新内存中的最新报价 (self.latest)
        - 控制台打印行情 (如果 print_tickers 为 True)
        - 将数据转发给当前活跃的 Runner (Grid/Arbitrage)
        """
        if hasattr(data, "symbol"):
            # TickerData 对象
            symbol = data.symbol
            ex = data.exchange
            bid = float(data.bid)
            ask = float(data.ask)
        else:
            # 字典兼容
            symbol = data["symbol"]
            ex = data["exchange"]
            bid = float(data["bid"])
            ask = float(data["ask"])

        entry = self.latest.setdefault(symbol, {})
        entry[ex] = {"bid": bid, "ask": ask}
        
        if self.print_tickers:
            key = f"{ex}:{symbol}"
            now = asyncio.get_event_loop().time()
            last = self._last_print_ts.get(key, 0.0)
            if now - last >= 1.0:
                logging.getLogger("cryptotrade.ticker").info(
                    "%s %s bid=%.4f ask=%.4f",
                    ex,
                    symbol,
                    bid,
                    ask,
                )
                self._last_print_ts[key] = now
        if self.runner:
            self.runner.on_ticker(data)

    async def start(self):
        """
        启动协调器
        - 加载配置并初始化交易所 Adapter
        - 区分真实交易所 (Binance) 与模拟交易所 (Mock)
        - 启动所有 Adapter 的 WebSocket 连接或模拟循环
        - 选定基准交易所 (Primary Exchange)
        - 初始化策略运行器 (Runner)
        """
        # 1️⃣ 加载策略 / 风控配置
        self.load_configs()
        # 2️⃣ 从策略中解析需要监控的交易对
        symbols = self.get_symbols()
        # 3️⃣ 遍历所有启用的交易所配置，创建对应的 Adapter (Mock 或 Real)
        configs = self._get_exchanges()

        # 检查是否启用了真实交易所（如 Binance），如果启用则不再加载 Mock 交易所
        has_real_exchange = False
        for conf in configs:
            name = conf["name"]
            ex_id = str(conf.get("exchange_id", name)).lower()
            is_binance = ex_id == "binance" or name.lower() == "binance"
            if is_binance:
                markets = conf.get("markets", {})
                if markets.get("spot", {}).get("enabled", False) or \
                   markets.get("USD-M Futures", {}).get("enabled", False):
                    has_real_exchange = True
                    break

        for conf in configs:
            name = conf["name"]
            ex_id = str(conf.get("exchange_id", name)).lower()
            is_binance = ex_id == "binance" or name.lower() == "binance"

            if is_binance:
                markets = conf.get("markets", {})
                spot_enabled = bool(markets.get("spot", {}).get("enabled", False))
                usdm_enabled = bool(markets.get("USD-M Futures", {}).get("enabled", False))

                if spot_enabled:
                    # 现货适配器订阅「策略 symbols」，由适配器内部进行规范化转换
                    m_spot = BinanceAdapter("binance-spot", symbols, {**conf, "markets": {"spot": {"enabled": True}, "USD-M Futures": {"enabled": False}}})
                    for s in symbols:
                        m_spot.subscribe(s, self.on_ticker)
                    self.exchanges["binance-spot"] = m_spot

                if usdm_enabled:
                    # U 本位适配器同样订阅「策略 symbols」，以便输出统一的策略符号
                    m_usdm = BinanceAdapter("binance-usdm", symbols, {**conf, "markets": {"spot": {"enabled": False}, "USD-M Futures": {"enabled": True}}})
                    for s in symbols:
                        m_usdm.subscribe(s, self.on_ticker)
                    self.exchanges["binance-usdm"] = m_usdm

                if not spot_enabled and not usdm_enabled and not has_real_exchange:
                    # 未启用任何市场，且无其他真实交易，回退为 Mock
                    m = MockExchange(name, symbols)
                    for s in symbols:
                        m.subscribe(s, self.on_ticker)
                    self.exchanges[name] = m
            else:
                # 如果已存在真实交易所，则跳过其他 Mock 交易所
                if has_real_exchange:
                    continue

                m = MockExchange(name, symbols)
                for s in symbols:
                    m.subscribe(s, self.on_ticker)
                self.exchanges[name] = m
        # 4️⃣ 标记运行状态，并启动所有 Exchange 的行情推送任务
        self.running = True
        for m in self.exchanges.values():
            await m.start()
        # 5️⃣ 选择一个基准交易所（优先使用 binance-spot，其次 binance-usdm）
        if "binance-spot" in self.exchanges:
            self.primary_exchange = "binance-spot"
        elif "binance-usdm" in self.exchanges:
            self.primary_exchange = "binance-usdm"
        else:
            self.primary_exchange = next(iter(self.exchanges.keys()), "")
        # 6️⃣ 重置基准价格，并初始化策略 Runner
        self.baseline = {}
        self._init_runner()

    def _init_runner(self):
        """
        初始化策略运行器
        - 根据配置的 type (grid_basic / arbitrage_segmented) 加载对应模块
        - 创建 Runner 实例并注入 Coordinator 引用
        """
        if not self.strategy_config.get("enabled", True):
            self.runner = None
            return

        t = self.strategy_type
        if t == "grid_basic":
            from cryptotrade.strategies.grid.runner import GridRunner
            self.runner = GridRunner(self)
        else:
            from cryptotrade.strategies.arbitrage.runner import ArbitrageRunner
            self.runner = ArbitrageRunner(self)

    async def stop(self):
        """
        停止系统
        - 停止所有交易所 Adapter (WebSocket 断开 / 模拟停止)
        - 取消相关任务
        """
        self.running = False
        for m in self.exchanges.values():
            await m.stop()

    async def run_cli(self, duration: float = 10.0):
        """
        运行 CLI 演示模式
        - 将主线程控制权交给 Runner 的 run_cli 方法
        - 在指定持续时间后结束
        """
        if self.runner:
            await self.runner.run_cli(duration)
