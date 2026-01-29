"""
CryptoTrade 学习项目 - REST API 测试入口

功能：
- 基于 aiohttp 的异步 REST API 交互
- 验证交易所连接配置（API Key/Secret）
- 测试核心交易接口（行情、余额、订单）
- 自动识别并适配现货/合约账户

使用方法：
    # 已在当前虚拟环境中开发安装：
    #   pip install -e .[async]
    #
    # 方式一：使用 console script
    #   cryptotrade-rest
    #
    # 方式二：以模块形式运行
    #   python -m cryptotrade.run_rest
"""

import asyncio
import logging
import yaml
from pathlib import Path
from decimal import Decimal

from cryptotrade.exchanges.cex.binance.rest import BinanceRest
from cryptotrade.core.adapters.models import TickerData, BalanceData, OrderBookData, PositionData, OrderData

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("RunREST")

def load_config():
    """加载 Binance 配置（支持路径锚定）"""
    # 🎛️ 路径锚定：确保在任何目录运行都能找到配置
    base_dir = Path(__file__).resolve().parent
    config_path = base_dir / "config/exchanges/cex/binance.yaml"
    
    if not config_path.exists():
        logger.warning(f"⚠️ 配置文件未找到: {config_path}，将使用默认配置（无 API Key）")
        return {}
    
    with open(config_path, "r", encoding="utf-8") as f:
        full_config = yaml.safe_load(f)
        # 如果配置包含 binance 根节点，提取内部配置
        if "binance" in full_config:
            return full_config["binance"]
        return full_config

async def main():
    """异步主函数：执行 REST API 连通性测试流程"""
    logger.info("🚀 开始测试 Binance REST API...")

    # 1️⃣ 加载配置
    config = load_config()
    
    # 2️⃣ 初始化 REST 客户端
    client = BinanceRest(config)
    
    if await client.initialize():
        try:
            # 3️⃣ 测试公共接口 (无需 API Key)
            symbol = "BTCUSDT"
            
            # 3.1 获取单个行情
            logger.info(f"\n📡 [1/5] 获取 {symbol} 行情...")
            ticker = await client.get_ticker(symbol)
            if ticker:
                logger.info(f"✅ 行情获取成功:")
                logger.info(f"   - 交易对: {ticker.symbol}")
                # logger.info(f"   - 最新价: {ticker.last}") # bookTicker 接口可能不返回 last
                logger.info(f"   - 买一价: {ticker.bid}")
                logger.info(f"   - 卖一价: {ticker.ask}")
                if isinstance(ticker, TickerData):
                    logger.info("   (数据类型验证通过: TickerData 对象)")
            else:
                logger.error("❌ 行情获取失败")

            # 3.2 获取深度信息
            logger.info(f"\n🌊 [2/5] 获取 {symbol} 深度(前5档)...")
            depth = await client.get_orderbook(symbol, limit=5)
            if depth:
                if isinstance(depth, OrderBookData):
                    logger.info(f"✅ 深度获取成功 (bids: {len(depth.bids)}, asks: {len(depth.asks)})")
                    if depth.bids:
                        # 优化后: 使用 tuple 索引访问 (price, size)
                        logger.info(f"   - 买一: {depth.best_bid[0]} (数量: {depth.best_bid[1]})")
                    if depth.asks:
                        logger.info(f"   - 卖一: {depth.best_ask[0]} (数量: {depth.best_ask[1]})")
                    logger.info("   (数据类型验证通过: OrderBookData 对象)")
                else:
                    logger.warning(f"⚠️ 返回类型不是 OrderBookData: {type(depth)}")
            else:
                logger.error("❌ 深度获取失败")
            
            # 4️⃣ 测试私有接口 (需配置 API Key)
            if client.api_key:
                # 4.1 获取账户余额
                logger.info("\n💰 [3/5] 测试私有接口: 获取账户余额...")
                try:
                    balances = await client.get_balances()
                    logger.info(f"✅ 余额获取成功 (共 {len(balances)} 种资产)")
                    for b in balances[:3]: # 只打印前3个
                        if isinstance(b, BalanceData):
                            logger.info(f"   - {b.currency}: 可用={b.free}, 冻结={b.used}")
                        else:
                            logger.info(f"   - {b}")
                except Exception as e:
                    logger.error(f"❌ 余额获取失败: {e}")

                # 4.2 获取当前挂单
                logger.info(f"\n📋 [4/5] 测试私有接口: 获取所有当前挂单 (自动聚合现货/合约/算法)...")
                try:
                    # 不传 symbol 以获取全量挂单
                    orders = await client.get_open_orders()
                    logger.info(f"✅ 挂单获取成功 (共 {len(orders)} 个)")
                    for o in orders:
                        if isinstance(o, OrderData):
                            logger.info(f"   - [{o.symbol}] [{o.side.value}] 价格: {o.price}, 数量: {o.amount}, 状态: {o.status.value}, ID: {o.id}")
                        else:
                            logger.info(f"   - {o}")
                except Exception as e:
                    logger.error(f"❌ 挂单获取失败: {e}")

                # 4.3 获取合约持仓 (如果启用合约市场)
                markets_conf = config.get("markets", {})
                use_usdm = bool(markets_conf.get("USD-M Futures", {}).get("enabled", False))
                if use_usdm:
                    logger.info("\n📊 [5/5] 测试合约接口: 获取合约持仓...")
                    try:
                        # 增加调试：同时打印 Account 接口的原始数据
                        logger.info("--- 调试信息: 正在获取 Account 信息以验证持仓 ---")
                        account_info = await client.get_futures_account_info()
                        if account_info:
                            logger.info(f"Account 接口返回 Keys: {list(account_info.keys())}")
                            if "positions" in account_info:
                                all_positions = account_info["positions"]
                                logger.info(f"Account 接口返回总持仓记录数: {len(all_positions)}")
                                
                                raw_positions = [
                                    p for p in all_positions
                                    if float(p.get("positionAmt", 0)) != 0
                                ]
                                logger.info(f"Account 接口返回非零持仓数: {len(raw_positions)}")
                                for p in raw_positions:
                                    logger.info(f"   >> {p['symbol']} Amt: {p['positionAmt']} Entry: {p['entryPrice']}")
                                
                                # 特别检查 HYPEUSDT
                                hype_pos = next((p for p in all_positions if "HYPE" in p.get("symbol", "")), None)
                                if hype_pos:
                                    logger.info(f"   >> HYPE相关持仓原始数据: {hype_pos}")
                                else:
                                    logger.info("   >> 未在 Account positions 中找到 HYPE 相关符号")
                            else:
                                logger.info("Account 接口未返回 positions 字段")
                        else:
                            logger.info("Account 接口返回为空")
                        logger.info("---------------------------------------------")

                        positions = await client.get_positions()
                        if positions:
                            logger.info(f"✅ 合约持仓获取成功 (共 {len(positions)} 个持仓)")
                            for pos in positions: # 打印所有持仓
                                if isinstance(pos, PositionData):
                                    logger.info(f"   - 交易对: {pos.symbol}")
                                    logger.info(f"   - 方向: {pos.side.value}")
                                    logger.info(f"   - 持仓数量: {pos.size}")
                                    logger.info(f"   - 平均入场价: {pos.entry_price}")
                                    logger.info(f"   - 未实现盈亏: {pos.unrealized_pnl}")
                                else:
                                    logger.info(f"   - {pos}")
                        else:
                            logger.info("   - 未持有任何合约持仓 (或获取失败)")
                    except Exception as e:
                        logger.error(f"❌ 合约持仓获取失败: {e}")
                else:
                    logger.info("\n⏭️ [5/5] 跳过合约持仓测试 (未启用合约市场)")

            else:
                logger.info("\n⏭️ [3/5]-[5/5] 跳过私有接口测试 (未配置 API Key)")

            logger.info("\n✨ 测试完成!")

        finally:
            await client.close()
    else:
        logger.error("初始化失败")

if __name__ == "__main__":
    asyncio.run(main())

def cli():
    """同步入口：供 `cryptotrade-rest` 等命令行直接调用"""
    # 🔁 把异步 main 包一层，方便作为 console script 入口
    asyncio.run(main())
