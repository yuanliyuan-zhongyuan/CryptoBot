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
from pathlib import Path
from typing import Dict, Any, List
import yaml
from .exchange import MockExchange


class TradingCoordinator:
    def __init__(self, cex_dir: Path, dex_dir: Path, strategy_config_path: Path, risk_config_path: Path):
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

    def load_configs(self):
        """加载策略与风控配置"""
        with open(self.strategy_config_path, "r", encoding="utf-8") as f:
            self.strategy_config = yaml.safe_load(f) or {}
        with open(self.risk_config_path, "r", encoding="utf-8") as f:
            self.risk_config = yaml.safe_load(f) or {}
        self.strategy_type = self.strategy_config.get("type", "arbitrage_segmented")

    def get_symbols(self) -> List[str]:
        """从策略配置中解析出需要监控的交易对列表"""
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

    def _get_exchanges(self) -> List[str]:
        """从 CEX/DEX 配置目录中解析出启用的交易所名称"""
        names: List[str] = []
        for d in [self.cex_dir, self.dex_dir]:
            if not d.exists():
                continue
            for p in d.glob("*.yaml"):
                with open(p, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if not data.get("enabled", True):
                    continue
                n = data.get("name") or p.stem
                names.append(n)
        return names

    def grid_params(self, symbol: str) -> Dict[str, Any]:
        """合并默认配置与单币种配置，得到网格参数"""
        default = self.strategy_config.get("default_config", {}).get("grid_config", {})
        sc = self.strategy_config.get("symbol_configs", {}).get(symbol, {})
        gc = sc.get("grid_config", {})
        return {
            "initial": gc.get("initial_spread_threshold", default.get("initial_spread_threshold", 0.02)),
            "step": gc.get("grid_step", default.get("grid_step", 0.01)),
            "max": gc.get("max_segments", default.get("max_segments", 5)),
        }

    def monitor_only(self) -> bool:
        """系统是否处于仅监控模式（不实际下单）"""
        return bool(self.strategy_config.get("system_mode", {}).get("monitor_only", True))

    def on_ticker(self, data: Dict[str, Any]):
        """行情回调：更新最新报价，并将数据转发给 Runner（预留）"""
        symbol = data["symbol"]
        ex = data["exchange"]
        entry = self.latest.setdefault(symbol, {})
        entry[ex] = {"bid": float(data["bid"]), "ask": float(data["ask"])}
        if self.runner:
            self.runner.on_ticker(data)

    async def start(self):
        """启动协调器：加载配置、创建 MockExchange、初始化 Runner"""
        # 1️⃣ 加载策略 / 风控配置
        self.load_configs()
        # 2️⃣ 从策略中解析需要监控的交易对
        symbols = self.get_symbols()
        # 3️⃣ 遍历所有启用的交易所配置，创建对应的 MockExchange
        for ex in self._get_exchanges():
            m = MockExchange(ex, symbols)
            for s in symbols:
                m.subscribe(s, self.on_ticker)
            self.exchanges[ex] = m
        # 4️⃣ 标记运行状态，并启动所有 MockExchange 的行情推送任务
        self.running = True
        for m in self.exchanges.values():
            await m.start()
        # 5️⃣ 选择一个基准交易所（当前简单选择第一个）
        self.primary_exchange = next(iter(self.exchanges.keys()), "")
        # 6️⃣ 重置基准价格，并初始化策略 Runner
        self.baseline = {}
        self._init_runner()

    def _init_runner(self):
        """根据策略类型选择并创建对应 Runner"""
        t = self.strategy_type
        if t == "grid_basic":
            from cryptotrade.strategies.grid.runner import GridRunner
            self.runner = GridRunner(self)
        else:
            from cryptotrade.strategies.arbitrage.runner import ArbitrageRunner
            self.runner = ArbitrageRunner(self)

    async def stop(self):
        """停止协调器：关闭所有 MockExchange 任务"""
        self.running = False
        for m in self.exchanges.values():
            await m.stop()

    async def run_cli(self, duration: float = 10.0):
        """运行 CLI 演示：将实际绘制/展示工作交给当前 Runner"""
        if self.runner:
            await self.runner.run_cli(duration)
