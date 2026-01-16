"""
arbitrage.runner - 跨交易所价差套利执行器（Runner）

职责：
- 从 Coordinator 读取每个交易对在各交易所的最新报价
- 调用 ArbitrageEngine 计算最优买入/卖出交易所及价差
- 按段位（segments）展示当前套利机会强度
"""

import asyncio
from typing import List
from .engine import ArbitrageEngine


class ArbitrageRunner:
    def __init__(self, coordinator):
        # 🔗 上层协调器引用：提供 latest 行情、网格参数等
        self.coordinator = coordinator
        # 🧮 套利计算引擎
        self.engine = ArbitrageEngine()

    def on_ticker(self, data):
        """预留的逐笔行情回调入口（未来可扩展事件驱动）"""
        # 当前 demo 使用的是定时轮询 + CLI 输出，这里暂时不做处理
        pass

    async def run_cli(self, duration: float = 10.0):
        """命令行套利监控主循环"""
        loop = asyncio.get_running_loop()
        start = loop.time()

        # 📌 当前关注的交易对列表
        symbols: List[str] = self.coordinator.get_symbols()

        while self.coordinator.running and loop.time() - start < duration:
            lines: List[str] = []

            for s in symbols:
                # 1️⃣ 从 Coordinator 拿到该交易对在所有交易所的最新报价
                quotes = self.coordinator.latest.get(s, {})

                # 2️⃣ 使用引擎计算价差以及最优买入/卖出交易所
                spread, bid_ex, ask_ex = self.engine.compute_spread(quotes)

                # 3️⃣ 使用与网格相同的参数结构，计算“触发段数”
                params = self.coordinator.grid_params(s)
                seg = self.engine.segments_triggered(params, spread)

                # 4️⃣ 判断当前是监控模式还是“实盘模式”
                mode = "Monitor" if self.coordinator.monitor_only() else "Live"

                # 5️⃣ 组装输出文案：价差 + 最优交易所
                if spread is not None:
                    lines.append(
                        f"{s} mode={mode} spread={spread:.4%} bid@{bid_ex} ask@{ask_ex}"
                    )
                else:
                    lines.append(f"{s} mode={mode} spread=NA")

                # 6️⃣ 输出基于价差的段位情况
                lines.append(
                    f"{s} segments={seg}/{params['max']} "
                    f"initial={params['initial']:.4%} step={params['step']:.4%}"
                )

                if spread is not None and seg > 0:
                    lines.append(f"{s} TRIGGER segments={seg}")

            # 7️⃣ 打印所有 symbol 当前的套利监控信息
            print("\n".join(lines))

            # 8️⃣ 控制刷新频率（每秒一次）
            await asyncio.sleep(1.0)

