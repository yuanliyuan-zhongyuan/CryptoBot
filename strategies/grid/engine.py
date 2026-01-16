"""
GridEngine - 网格策略核心计算引擎

职责：
- 计算当前价格相对基准价的变化幅度（百分比）
- 根据变化幅度和参数(initial/step/max) 计算触发的网格段数
- 不关心具体交易所/执行，只做纯计算逻辑
"""

from typing import Optional


class GridEngine:
    def grid_change(self, mid: float, baseline: Optional[float]) -> Optional[float]:
        """计算中间价相对基准价的变动比例

        返回值：
        - 0.0：基准价为空时（第一次初始化），视作无变化
        - None：基准价为 0 时无法计算，直接跳过
        - 其他：绝对变化比例，例如 0.02 表示 2% 变化
        """
        # 🧮 处理基准价缺失/为 0 的边界情况
        if baseline is None:
            return 0.0
        if baseline == 0:
            return None

        # 📊 计算百分比变化
        return abs(mid - baseline) / baseline

    def segments_triggered(self, params: dict, value: Optional[float]) -> int:
        """根据变化幅度计算触发的网格段数

        params:
        - initial: 起始触发阈值（例如 0.01 -> 1%）
        - step: 每多一段所需额外变化（例如 0.005 -> 0.5%）
        - max: 最大网格段数上限
        """
        # ❌ 无法计算变化（例如 baseline 为 0）时，不触发任何网格
        if value is None:
            return 0

        seg = 0
        thr = params["initial"]

        # 🔁 逐段累加，只要变化超过当前阈值，就再多触发一段
        while seg < params["max"] and value >= thr:
            seg += 1
            thr += params["step"]

        return seg


