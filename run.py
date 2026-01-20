"""
CryptoTrade 学习项目 - 最小可运行入口

功能：
- 基于 CEX/DEX 配置的多交易所行情模拟
- 通过 Coordinator / Runner / Engine 协调执行策略
- 默认演示「网格监控」策略，可切换为套利等策略

使用方法：
    # 已在当前虚拟环境中开发安装：
    #   python -m pip install -e cryptotrade
    #
    # 方式一：使用 console script
    #   cryptotrade-run
    #
    # 方式二：以模块形式运行
    #   python -m cryptotrade.run --duration 10
"""

import asyncio
import argparse
from pathlib import Path
from cryptotrade.core.trading_coordinator import TradingCoordinator


def parse_args():
    """解析命令行参数（仅负责收集用户输入，不做业务逻辑）"""
    # 🎛️ 基本说明：这里的参数只是把「外部世界」的信息收集进来
    # - cex-dir / dex-dir：分别指向 CEX / DEX 的 YAML 配置目录
    # - strategy：策略配置文件（决定使用网格 / 套利等策略）
    # - risk：风险配置文件（最大仓位、最大亏损等）
    # - duration：运行时长（秒），方便你在学习阶段控制演示时间
    p = argparse.ArgumentParser(description="CryptoTrade - Coordinator/Runner/Engine 示例入口")
    base = Path(__file__).resolve().parent
    p.add_argument("--cex-dir", type=Path, default=base / "config/exchanges/cex")
    p.add_argument("--dex-dir", type=Path, default=base / "config/exchanges/dex")
    p.add_argument("--strategy", type=Path, default=base / "config/strategies/grid/basic_grid.yaml")
    p.add_argument("--risk", type=Path, default=base / "config/risk/risk.yaml")
    p.add_argument("--duration", type=float, default=10.0, help="运行时长（秒），学习演示用")
    return p.parse_args()


async def main():
    """异步主函数：负责把参数和核心协调器串起来"""
    # 1️⃣ 解析外部参数
    args = parse_args()
    # 2️⃣ 创建交易协调器（TradingCoordinator）
    #    - 内部会加载策略 / 风控配置
    #    - 扫描 CEX/DEX YAML，创建对应的 MockExchange
    #    - 根据策略类型选择合适的 Runner（网格 / 套利）
    orch = TradingCoordinator(
        cex_dir=args.cex_dir,
        dex_dir=args.dex_dir,
        strategy_config_path=args.strategy,
        risk_config_path=args.risk,
    )
    # 3️⃣ 启动系统（订阅行情 + 初始化策略 Runner）
    await orch.start()
    try:
        # 4️⃣ 运行 CLI 演示：
        #    - 每秒输出当前 symbol 的监控信息
        #    - 展示网格段位/跨交易所价差等触发情况
        await orch.run_cli(args.duration)
    finally:
        # 5️⃣ 优雅关闭（停止所有 MockExchange 等任务）
        await orch.stop()


def cli():
    """同步入口：供 `cryptotrade-run` 等命令行直接调用"""
    # 🔁 把异步 main 包一层，方便作为 console script 入口
    asyncio.run(main())


if __name__ == "__main__":
    cli()

