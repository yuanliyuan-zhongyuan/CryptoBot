"""
grid 策略包

模块划分：
- engine: 网格触发计算逻辑（纯函数计算，不依赖外部状态）
- runner: 网格策略执行/监控逻辑（依赖 Coordinator 提供行情与配置）
"""

__all__ = ["engine", "runner"]

