"""
ArbitrageEngine - 跨交易所价差套利计算引擎

职责：
- 在多个交易所报价中找到“最高买价交易所”和“最低卖价交易所”
- 计算两者之间的相对价差（作为套利空间）
- 按 initial/step/max 逻辑计算当前触发的套利段数
"""

from typing import Dict, Optional, Tuple


class ArbitrageEngine:
    def compute_spread(
        self, quotes: Dict[str, Dict[str, float]]
    ) -> Tuple[Optional[float], str, str]:
        """计算跨交易所价差及对应买入/卖出交易所

        返回：
        - spread: 相对价差（例如 0.02 表示 2% 套利空间）
        - best_bid_ex: 卖出（做空/平仓）交易所名称
        - best_ask_ex: 买入（开仓）交易所名称
        """
        # ⚠️ 行情不足两个交易所时，不存在真正的跨交易所价差
        if not quotes or len(quotes) < 2:
            return None, "", ""

        best_bid = -1.0
        best_bid_ex = ""
        best_ask = 0.0
        best_ask_ex = ""

        # 1️⃣ 找到全市场最高买价及其交易所
        for ex, v in quotes.items():
            if v["bid"] > best_bid:
                best_bid = v["bid"]
                best_bid_ex = ex

        # 2️⃣ 找到全市场最低卖价及其交易所
        best_ask = min(v["ask"] for v in quotes.values())
        for ex, v in quotes.items():
            if v["ask"] == best_ask:
                best_ask_ex = ex
                break

        # 3️⃣ 保护：避免除以 0
        if best_ask == 0:
            return None, "", ""

        # 4️⃣ 计算相对价差
        spread = (best_bid - best_ask) / best_ask
        return spread, best_bid_ex, best_ask_ex

    def segments_triggered(self, params: Dict, spread: Optional[float]) -> int:
        """根据价差大小计算触发的套利段数"""
        if spread is None:
            return 0

        seg = 0
        thr = params["initial"]

        # 🔁 与网格逻辑类似：价差每跨过一个 step，就多触发一段
        while seg < params["max"] and spread >= thr:
            seg += 1
            thr += params["step"]

        return seg

