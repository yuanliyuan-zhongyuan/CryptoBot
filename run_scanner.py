"""
==============================================================================
🚀  雷达扫描器启动脚本 (Scanner Entry Point)
==============================================================================

🎯 模块作用
- 作为雷达扫描服务的独立入口，提供可视化的实时行情看板
- 演示 "配置 -> 发现 -> 订阅" 的完整工作流
- 负责初始化 REST 客户端、加载配置、驱动扫描循环、渲染 UI

🔌 使用场景
- 开发调试: 观察 ScannerService 的筛选逻辑是否符合预期
- 实盘辅助: 作为一个独立的行情监控大屏，挂在副屏上实时寻找机会
- 策略验证: 验证 binance_scanner.yaml 配置文件的效果

📥 输入 / 📤 输出
- 输入: 配置文件 (binance.yaml, binance_scanner.yaml)
- 输出: 终端实时刷新界面 (Rich UI)，展示现货/合约 Top N 榜单

🧭 运行流程
1. 加载配置 (Binance API & Scanner 策略)
2. 初始化 BinanceRest 客户端 (连接性检查)
3. 启动 Rich Live 界面上下文
4. 进入主循环 (While True):
   - ⏳ 检查热更新: 是否有新的配置变更
   - 📡 执行扫描: 并行调用 scan_spot / scan_futures
   - 📊 渲染 UI: 更新现货/合约双榜单
   - 💤 等待: 智能休眠，防止 API 限频
   
🗂️ 配置速查
- 启动命令: python -m cryptotrade.run_scanner
- 配置文件: config/scanner/cex/binance_scanner.yaml
==============================================================================
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
    """
    🔄 单独加载 Scanner 策略配置 (用于热更新)
    
    从 config/scanner/cex/binance_scanner.yaml 读取最新配置。
    此函数设计为轻量级，以便在主循环中高频调用。
    """
    base_dir = Path(__file__).resolve().parent
    scanner_conf = {}
    scanner_path = base_dir / "config/scanner/cex/binance_scanner.yaml"
    if scanner_path.exists():
        with open(scanner_path, "r", encoding="utf-8") as f:
            full = yaml.safe_load(f)
            scanner_conf = full.get("binance_scanner", {})
    return scanner_conf

def load_config():
    """
    ⚙️ 加载系统配置
    
    同时加载基础 API 配置和 Scanner 策略配置。
    :return: (binance_conf, scanner_conf) 元组
    """
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
    """
    🎨 创建单个扫描结果表格 (UI 组件)
    
    使用 Rich 库构建美观的终端表格。
    
    :param title: 表格标题
    :param results: 扫描结果列表 List[ScanResult]
    :param style: 边框颜色风格
    :return: Rich Table 对象
    """
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
    """
    📐 生成整体布局 (UI 容器)
    
    组合 标题面板 + 现货表格 + 合约表格。
    
    :param spot_results: 现货扫描结果
    :param futures_results: 合约扫描结果
    :param last_update: 最后更新时间字符串
    :param interval: 当前扫描间隔
    :param limit: 显示数量限制
    :return: Rich Group 对象 (可直接渲染)
    """
    
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
    """
    🎬 主流程入口
    
    1. 初始化环境与客户端
    2. 执行安全检查 (IP 限频预警)
    3. 启动 UI 渲染循环
    4. 协调扫描任务与配置热更新
    """
    
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
