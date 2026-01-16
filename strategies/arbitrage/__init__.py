"""
arbitrage 策略包

模块划分：
- engine: 套利价差与段位计算逻辑（纯计算）
- runner: 读取多交易所报价，进行命令行监控/展示
"""

__all__ = ["engine", "runner"]

