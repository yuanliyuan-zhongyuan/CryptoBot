"""
grid.runner - 网格策略执行器（Runner）

职责：
- 从 Coordinator 读取最新行情与网格参数
- 调用 GridEngine 进行价格变化与网格段位计算
- 以命令行形式打印当前监控状态（学习/演示用）
"""

import asyncio
from typing import List
from .engine import GridEngine


class GridRunner:
    def __init__(self, coordinator):
        # 🔗 上层协调器引用：提供行情、网格参数、运行状态等
        self.coordinator = coordinator
        # 🧮 网格计算引擎（纯计算逻辑）
        self.engine = GridEngine()

    def on_ticker(self, data):
        """预留的逐笔行情回调（未来可扩展为事件驱动模式）"""
        # 当前最小 demo 使用定时轮询 + CLI 输出，这里先占位
        pass

    async def run_cli(self, duration: float = 10.0):
        """命令行网格监控主循环"""
        loop = asyncio.get_running_loop()
        start = loop.time()

        # 📌 当前需要监控的交易对列表
        symbols: List[str] = self.coordinator.get_symbols()

        while self.coordinator.running and loop.time() - start < duration:
            lines: List[str] = []

            for s in symbols:
                # 1️⃣ 取出主交易所的最新行情
                v = self.coordinator.latest.get(s, {}).get(self.coordinator.primary_exchange)

                if v:
                    # 2️⃣ 计算中间价并维护基准价
                    mid = (v["bid"] + v["ask"]) / 2.0
                    baseline = self.coordinator.baseline.get(s)
                    if baseline is None:
                        # 首次出现时，用当前价格作为基准
                        self.coordinator.baseline[s] = mid
                        baseline = mid

                    # 3️⃣ 计算价格变化比例
                    chg = self.engine.grid_change(mid, baseline)
                else:
                    chg = None

                # 4️⃣ 读取网格参数，计算触发的段数
                params = self.coordinator.grid_params(s)
                seg = self.engine.segments_triggered(params, chg)

                # 5️⃣ 根据配置决定当前是监控模式还是“实盘”模式
                mode = "Monitor" if self.coordinator.monitor_only() else "Live"

                # 6️⃣ 组装输出文案
                if chg is not None:
                    lines.append(
                        f"{s} mode={mode} change={chg:.4%} base@{self.coordinator.primary_exchange}"
                    )
                else:
                    lines.append(f"{s} mode={mode} change=NA")

                lines.append(
                    f"{s} segments={seg}/{params['max']} "
                    f"initial={params['initial']:.4%} step={params['step']:.4%}"
                )

                if chg is not None and seg > 0:
                    lines.append(f"{s} TRIGGER segments={seg}")

            # 7️⃣ 一次性打印当前所有 symbol 的监控信息
            print("\n".join(lines))

            # 8️⃣ 控制刷新频率（每秒一次）
            await asyncio.sleep(1.0)


