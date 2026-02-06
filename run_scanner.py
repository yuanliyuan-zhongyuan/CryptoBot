"""
CryptoTrade 学习项目 - 全币种扫描器入口
=======================================

功能：
- 🚀 启动 REST 客户端和订阅管理器
- ⚙️ 读取配置文件，识别已启用的市场 (现货/合约)
- 🔍 自动扫描所有处于交易状态的币种 (Full Market Scan)
- 📊 使用 Rich Live 持续刷新展示结果 (现货 & 合约双表)
- 📝 演示 "配置 -> 发现 -> 订阅" 的完整流程

使用方法：
    python -m cryptotrade.run_scanner
"""

import asyncio
import logging
import yaml
import time
from pathlib import Path
from typing import List, Dict, Tuple
from decimal import Decimal

# Rich 库导入
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich import box

from cryptotrade.exchanges.cex.binance.rest import BinanceRest
from cryptotrade.core.adapters.subscription_manager import SubscriptionManager
from cryptotrade.core.services.scanner import ScannerService, ScanResult

# 配置日志
logging.basicConfig(
    level=logging.INFO, # 降低日志级别以避免干扰 UI
    format="%(asctime)s - %(levelname)s - %(message)s"
)
# 单独为 Scanner 设置 INFO 级别，但输出到文件或忽略 (为了 UI 整洁，暂时忽略)
logger = logging.getLogger("RunScanner")

# 初始化 Rich Console
console = Console()

def load_scanner_config():
    """单独加载 Scanner 策略配置 (用于热更新)"""
    base_dir = Path(__file__).resolve().parent
    scanner_conf = {}
    scanner_path = base_dir / "config/scanner/cex/binance_scanner.yaml"
    if scanner_path.exists():
        with open(scanner_path, "r", encoding="utf-8") as f:
            full = yaml.safe_load(f)
            scanner_conf = full.get("binance_scanner", {})
    return scanner_conf

def load_config():
    """加载配置 (Binance API + Scanner)"""
    base_dir = Path(__file__).resolve().parent
    
    # 1. 加载 Binance API 配置 (用于 REST Client)
    binance_conf = {}
    binance_path = base_dir / "config/exchanges/cex/binance.yaml"
    if binance_path.exists():
        with open(binance_path, "r", encoding="utf-8") as f:
            full = yaml.safe_load(f)
            binance_conf = full.get("binance", {})
            
    # 2. 加载 Scanner 策略配置
    scanner_conf = load_scanner_config()
            
    return binance_conf, scanner_conf

def create_table(title: str, results: List[ScanResult], style: str = "blue") -> Table:
    """创建单个扫描结果表格"""
    if not results:
        # 空结果表格
        table = Table(title=title, box=box.ROUNDED, border_style=style, expand=True)
        table.add_column("提示", justify="center")
        table.add_row("⚠️ 未发现符合条件的交易机会")
        return table

    table = Table(title=title, box=box.ROUNDED, header_style=f"bold {style}", border_style=style, expand=True)

    table.add_column("排名", justify="center", style="dim", width=6)
    table.add_column("交易对", style="bold white")
    table.add_column("现价 (USDT)", justify="right")
    table.add_column("24h 涨跌幅", justify="right")
    table.add_column("24h 成交额 (万)", justify="right")
    table.add_column("24h 高/低", justify="right", style="dim")

    for idx, item in enumerate(results, 1):
        # 涨跌幅颜色处理
        change_color = "green" if item.change_24h >= 0 else "red"
        change_icon = "🚀" if item.change_24h >= 10 else ("📈" if item.change_24h >= 0 else "📉")
        
        # 价格格式化
        price_str = f"{item.price:.4f}" if item.price < 1 else f"{item.price:.2f}"
        if item.price < 0.0001:
             price_str = f"{item.price:.8f}"

        # 成交额格式化 (万)
        vol_wan = item.volume_24h / 10000
        
        table.add_row(
            str(idx),
            item.symbol,
            price_str,
            f"[{change_color}]{change_icon} {item.change_24h:+.2f}%[/{change_color}]",
            f"{vol_wan:.0f}",
            f"{item.high_24h:.4f} / {item.low_24h:.4f}"
        )
    return table

def generate_layout(spot_results: List[ScanResult], futures_results: List[ScanResult], last_update: str, interval: int, limit: int = 10) -> Group:
    """生成整体布局 (Group)"""
    
    header = Panel(
        Text(f"🚀 CryptoTrade 全币种雷达扫描器 (Radar Mode) | 刷新: {interval}s | 最后更新: {last_update}", justify="center", style="bold magenta"),
        style="magenta"
    )
    
    spot_table = create_table(f"📊 现货市场波动榜 (Spot Top {limit})", spot_results, style="cyan")
    futures_table = create_table(f"📊 U本位合约波动榜 (Futures Top {limit})", futures_results, style="green")
    
    return Group(
        header,
        spot_table,
        Text(" "), # Spacer
        futures_table,
        Text("按 Ctrl+C 停止扫描...", style="dim italic", justify="center")
    )

async def main():
    """主流程"""
    
    # 1. 加载配置
    binance_conf, scanner_conf = load_config()
    
    # 获取扫描设置
    scan_settings = scanner_conf.get("scan", {})
    interval = scan_settings.get("interval", 60)
    min_safe_interval = scan_settings.get("min_safe_interval", 30)
    limit = scan_settings.get("limit", 10)
    
    # IP 安全检查
    if interval < min_safe_interval:
        console.print(f"[bold red]⚠️ 警告: 扫描间隔 ({interval}s) 低于安全阈值 ({min_safe_interval}s)！[/bold red]")
        console.print(f"[bold red]频繁扫描可能导致 IP 被交易所封禁。建议修改配置。[/bold red]")
        console.print(f"5秒后继续...")
        await asyncio.sleep(5)

    if "subscription" not in binance_conf:
        binance_conf["subscription"] = {}
    binance_conf["subscription"]["mode"] = "dynamic"
    
    client = BinanceRest(binance_conf)
    # 将 scanner_conf 传给 Service
    scanner = ScannerService(client, scanner_conf)
    
    console.print(f"[yellow]正在初始化连接... (扫描间隔: {interval}秒)[/yellow]")
    if not await client.initialize():
        console.print("[red]❌ 客户端初始化失败[/red]")
        return

    try:
        # 使用 Live Context Manager 实现持续刷新
        last_scan_time = 0
        config_checked_for_this_cycle = False
        spot_results = []
        futures_results = []
        scan_finished_time_str = "等待首次扫描..."
        
        with Live(console=console, screen=True, refresh_per_second=1) as live:
            while True:
                now = time.time()
                # 计算下一次扫描的理论时间
                # 如果是首次运行(last_scan_time=0)，next_scan_time会很小，触发立即扫描
                next_scan_time = last_scan_time + interval
                time_until_scan = next_scan_time - now
                
                # 🔄 异步热重载配置：在距离下次扫描前 2 秒内执行
                # 首次运行不检查(因为启动时已加载)
                if last_scan_time > 0 and time_until_scan <= 2 and not config_checked_for_this_cycle:
                    try:
                        loop = asyncio.get_running_loop()
                        new_scanner_conf = await loop.run_in_executor(None, load_scanner_config)
                        
                        if new_scanner_conf:
                            # 1. 更新 Service 配置
                            scanner.update_config(new_scanner_conf)
                            
                            # 2. 更新本地控制变量
                            scan_settings = new_scanner_conf.get("scan", {})
                            new_interval = scan_settings.get("interval", 60)
                            new_limit = scan_settings.get("limit", 10)
                            
                            if new_interval != interval:
                                interval = new_interval
                            if new_limit != limit:
                                limit = new_limit
                        
                        config_checked_for_this_cycle = True
                    except Exception as e:
                        logger.error(f"热更新配置失败: {e}")

                # 3. 检查是否需要扫描
                if now >= next_scan_time:
                    try:
                        # 并行扫描
                        spot_task = asyncio.create_task(scanner.scan_spot(limit=limit))
                        futures_task = asyncio.create_task(scanner.scan_futures(limit=limit))
                        
                        spot_results, futures_results = await asyncio.gather(spot_task, futures_task)
                        
                        # 更新状态
                        last_scan_time = time.time()
                        scan_finished_time_str = time.strftime("%H:%M:%S", time.localtime(last_scan_time))
                        config_checked_for_this_cycle = False # 重置标记，准备下一个周期
                        
                    except Exception as e:
                        live.update(Panel(f"❌ 扫描出错: {e}", style="red"))
                        # 出错后稍等，避免死循环重试
                        await asyncio.sleep(5)
                        # 出错也视为一次尝试，重置时间防止立即重试
                        last_scan_time = time.time() 
                        continue

                # 4. 始终更新 UI (保持间隔显示刷新)
                # 注意：这里传入的是 scan_finished_time_str 而不是当前时间
                layout = generate_layout(spot_results, futures_results, scan_finished_time_str, interval, limit)
                live.update(layout)

                # 5. 短暂休眠 (保持 UI 响应)
                await asyncio.sleep(1)
 
                    
    except KeyboardInterrupt:
        console.print("[yellow]扫描已停止[/yellow]")
    except Exception as e:
        logger.error(f"运行出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()

def cli():
    """CLI 入口点"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    cli()
