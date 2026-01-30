"""
CryptoTrade 学习项目 - 策略运行入口

功能：
- 系统的核心启动脚本，负责组装各个组件（Coordinator, Runner, Engine）。
- 自动加载配置、连接交易所（真实/Mock）、启动策略循环。
- 提供 CLI 界面实时展示策略状态（如网格监控、套利价差）。

使用方法：
    # 已在当前虚拟环境中开发安装：
    #   pip install -e .[async]
    #
    # 方式一：使用 console script (推荐)
    #   cryptotrade-run --duration 60
    #
    # 方式二：以模块形式运行
    #   python -m cryptotrade.run --strategy config/strategies/grid/classic.yaml
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path
from cryptotrade.core.coordinators.trading_coordinator import TradingCoordinator

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Run")

def parse_args():
    """解析命令行参数"""
    # 🎛️ 参数解析：负责收集运行所需的外部配置路径和控制参数
    p = argparse.ArgumentParser(description="🚀 CryptoTrade 策略运行器")
    
    # 智能路径锚定：以当前脚本位置为基准，自动寻找默认配置目录
    # 这样无论你在哪里运行脚本，都能找到 config 目录
    base = Path(__file__).resolve().parent
    
    p.add_argument("--cex-dir", type=Path, default=base / "config/exchanges/cex", help="CEX 交易所配置目录")
    p.add_argument("--dex-dir", type=Path, default=base / "config/exchanges/dex", help="DEX 交易所配置目录")
    p.add_argument("--strategy", type=Path, default=base / "config/strategies/grid/basic_grid.yaml", help="策略配置文件路径")
    p.add_argument("--risk", type=Path, default=base / "config/risk/risk.yaml", help="风控配置文件路径")
    p.add_argument("--duration", type=float, default=60.0, help="运行时长(秒)，设为 -1 则无限运行")
    
    return p.parse_args()

async def main():
    """异步主函数：系统生命周期管理"""
    args = parse_args()
    
    logger.info("==================================================")
    logger.info("🚀 启动 CryptoTrade 策略运行器")
    logger.info("==================================================")
    logger.info(f"📂 策略配置: {args.strategy.name}")
    logger.info(f"📂 交易所配置: {args.cex_dir.name}")
    logger.info(f"⏱️  计划运行: {args.duration} 秒 {'(无限模式)' if args.duration < 0 else ''}")
    
    # 1️⃣ 初始化协调器 (TradingCoordinator)
    #    它是系统的"大脑"，负责：
    #    - 加载所有配置
    #    - 实例化交易所适配器 (Adapter)
    #    - 初始化策略 Runner (网格/套利)
    try:
        orch = TradingCoordinator(
            cex_dir=args.cex_dir,
            dex_dir=args.dex_dir,
            strategy_config_path=args.strategy,
            risk_config_path=args.risk,
        )
    except Exception as e:
        logger.error(f"❌ 初始化失败: {e}")
        return

    # 2️⃣ 启动系统
    #    - 建立 WebSocket 连接
    #    - 订阅行情数据
    #    - 启动策略计算循环
    logger.info("\n🔌 正在连接交易所并订阅行情...")
    await orch.start()
    
    try:
        # 3️⃣ 运行 CLI 监控界面
        #    - 实时打印 Ticker / OrderBook 信息
        #    - 监控策略触发信号
        logger.info("✅ 系统已启动! 按 Ctrl+C 可随时停止。\n")
        await orch.run_cli(args.duration if args.duration > 0 else float('inf'))
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️  检测到用户停止信号 (Ctrl+C)")
        
    except Exception as e:
        logger.error(f"\n❌ 运行时发生错误: {e}", exc_info=True)
        
    finally:
        # 4️⃣ 优雅关闭
        #    - 关闭 WebSocket 连接
        #    - 取消所有异步任务
        logger.info("\n🛑 正在关闭系统，请稍候...")
        await orch.stop()
        logger.info("👋 再见!")

def cli():
    """Console Script 入口"""
    try:
        # Windows 下 ProactorEventLoop 通常性能更好且支持 subprocess
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass # 避免在这里再次打印 traceback

if __name__ == "__main__":
    cli()
