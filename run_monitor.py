"""
CryptoTrade 学习项目 - 实时价格监控入口

功能：
- 基于 WebSocket 的实时价格监控
- 支持现货 (Spot) 和 U本位合约 (Futures) 混合监控
- 使用 Rich 库展示实时终端界面
- 自动识别符号格式适配不同数据源 (Spot: BTC/USDT, Futures: BTCUSDT)

使用方法：
    # 方式一：直接运行模块
    python -m cryptotrade.run_monitor
    
    # 方式二：作为脚本运行 (需确保路径正确)
    # python cryptotrade/run_monitor.py
"""

import asyncio
import logging
import sys
import time
import copy
import yaml
from pathlib import Path
from typing import Dict, List, Tuple

from rich.console import Console
from rich.table import Table
from rich.live import Live

from cryptotrade.exchanges.cex.binance.websocket import BinanceWebSocket
from cryptotrade.core.services.monitor import PriceMonitorService

# 配置日志 (UI模式下只记录错误，避免打乱界面)
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("RunMonitor")

def load_alert_config() -> Dict:
    """加载报警配置（支持路径锚定）"""
    # 🎛️ 路径锚定：确保在任何目录运行都能找到配置
    base_dir = Path(__file__).resolve().parent
    config_path = base_dir / "config/alert/cex/binance_alert.yaml"
    
    if not config_path.exists():
        console = Console()
        console.print(f"[bold red]⚠️ 配置文件未找到: {config_path}，将使用默认配置[/]")
        logger.warning(f"⚠️ 配置文件未找到: {config_path}，将使用默认配置")
        return {
            "symbols": [
                {"symbol": "BTC/USDT", "volatility": {"enabled": True, "window": 60, "threshold": 0.5}},
                {"symbol": "ETH/USDT", "volatility": {"enabled": True, "window": 60, "threshold": 0.5}}
            ]
        }
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            # print(f"DEBUG: Config loaded: {config.keys() if config else 'None'}") # Debug
            if config:
                # 优先查找 binance_alert 配置块
                if "binance_alert" in config:
                    # print("DEBUG: Found binance_alert block") # Debug
                    return config["binance_alert"]
                elif "price_alert" in config:
                    return config["price_alert"]
                return config
    except Exception as e:
        console = Console()
        console.print(f"[bold red]⚠️ 加载配置 {config_path} 失败: {e}[/]")
        logger.error(f"⚠️ 加载配置 {config_path} 失败: {e}")
        return {}
    
    return {}

def load_binance_config() -> Dict:
    """加载 Binance 交易所配置"""
    # 🎛️ 路径锚定
    base_dir = Path(__file__).resolve().parent
    config_path = base_dir / "config/exchanges/cex/binance.yaml"

    if not config_path.exists():
        logger.error(f"❌ Binance 配置文件未找到: {config_path}")
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data:
                if "binance" in data: return data["binance"]
                if "api" in data: return data
    except Exception as e:
        logger.error(f"⚠️ 加载 {config_path} 失败: {e}")
    
    return {}

def create_market_config(base_conf: Dict, is_futures: bool) -> Dict:
    """创建特定市场的配置副本 (强制开启/关闭合约模式)"""
    conf = copy.deepcopy(base_conf)
    if "markets" not in conf:
        conf["markets"] = {}
    
    # 显式开关 U本位合约
    if "USD-M Futures" not in conf["markets"]:
        conf["markets"]["USD-M Futures"] = {}
        
    conf["markets"]["USD-M Futures"]["enabled"] = is_futures
    
    # 现货开关
    if "spot" not in conf["markets"]:
        conf["markets"]["spot"] = {}
    conf["markets"]["spot"]["enabled"] = not is_futures
    
    return conf

def generate_table(service: PriceMonitorService, service_config: Dict) -> Table:
    """生成监控表格（支持动态列与自定义颜色）"""
    # 1. 获取配置
    display_conf = service_config.get("display", {})
    colors = display_conf.get("colors", {})
    
    # 颜色定义 (带默认值)
    c_up = colors.get("price_up", "green")
    c_down = colors.get("price_down", "red")
    c_alert = colors.get("alert", "yellow")
    c_normal = colors.get("normal", "white")
    
    table = Table(title="🚀 CryptoTrade 价格监控 (WebSocket Real-time)", border_style="blue")
    
    # 2. 确定显示的列
    # 如果配置中未指定，使用默认列组合
    show_columns = display_conf.get("show_columns")
    if not show_columns:
        # 默认列组合 (更新为包含 high_low)
        show_columns = [
            "symbol", "price", "change_24h", "change_window", 
            "high_low", # 默认显示 24h 高低
            "price_target_upper", "price_target_lower",
            "alert_count", "last_update"
        ]

    # 3. 动态添加表头
    for col in show_columns:
        if col == "symbol":
            table.add_column("代币", style=c_normal, no_wrap=True)
        elif col == "price":
            table.add_column("当前价格", justify="right") # 样式动态
        elif col == "change_24h":
            table.add_column("24h 涨跌", justify="right")
        elif col == "change_window":
            table.add_column("窗口波动", justify="right")
        elif col == "high_low":
            table.add_column("24h 高/低", justify="right", style="dim")
        elif col == "price_target_upper":
            table.add_column("目标上限", justify="right", style="dim")
        elif col == "price_target_lower":
            table.add_column("目标下限", justify="right", style="dim")
        elif col == "alert_count":
            table.add_column("报警次数", justify="right", style=c_alert)
        elif col == "last_update":
            table.add_column("更新时间", justify="right", style="dim")
        else:
            table.add_column(col, justify="right")

    # 4. 填充数据
    for s_conf in service_config.get("symbols", []):
        symbol = s_conf["symbol"]
        stats = service.statistics.get(symbol)
        
        if not stats:
            continue

        # 预计算关键数据
        change_24h = stats.change_percent_24h
        # 决定该行的基础颜色倾向 (涨/跌)
        row_color = c_up if change_24h > 0 else c_down
        
        row_cells = []
        for col in show_columns:
            if col == "symbol":
                row_cells.append(symbol)
                
            elif col == "price":
                # 价格显示
                p_val = stats.current_price
                p_str = f"{p_val:,.2f}" if p_val > 1 else f"{p_val:,.4f}"
                row_cells.append(f"[{row_color}]{p_str}[/]")
                
            elif col == "change_24h":
                row_cells.append(f"[{row_color}]{change_24h:+.2f}%[/]")
                
            elif col == "change_window":
                win_conf = s_conf.get("volatility", {})
                win_sec = win_conf.get("window", 60)
                win_change = stats.get_window_change(win_sec)
                
                if win_change is None:
                    row_cells.append("-")
                else:
                    wc_color = c_up if win_change > 0 else c_down
                    # 检查是否超过阈值
                    if abs(win_change) >= win_conf.get("threshold", 1.0):
                        # 触发报警样式: 粗体 + 报警色 + 反转
                        cell_str = f"[bold {c_alert} reverse]{win_change:+.2f}%[/]"
                    else:
                        cell_str = f"[{wc_color}]{win_change:+.2f}%[/]"
                    row_cells.append(cell_str)
            
            elif col == "high_low":
                h_val = stats.high_24h
                l_val = stats.low_24h
                if h_val == 0 and l_val == 0:
                    row_cells.append("-")
                else:
                    fmt = ",.2f" if h_val > 1 else ",.4f"
                    row_cells.append(f"{h_val:{fmt}} / {l_val:{fmt}}")
            
            elif col == "price_target_upper":
                upper = s_conf.get("price_target", {}).get("upper", 0)
                row_cells.append(str(upper) if upper > 0 else "-")
                
            elif col == "price_target_lower":
                lower = s_conf.get("price_target", {}).get("lower", 0)
                row_cells.append(str(lower) if lower > 0 else "-")
                
            elif col == "alert_count":
                row_cells.append(str(stats.total_alerts))
                
            elif col == "last_update":
                t_str = stats.last_update_time.strftime("%H:%M:%S") if stats.last_update_time else "-"
                row_cells.append(t_str)
            
            else:
                row_cells.append("?")

        table.add_row(*row_cells)

    # 统计总报警次数
    total_alerts = sum(s.total_alerts for s in service.statistics.values())
    
    # 获取刷新间隔配置
    refresh_interval = display_conf.get("refresh_interval", 1)
    
    table.caption = f"[bold {c_alert}]报警: {total_alerts}次[/] | [dim]刷新: {refresh_interval}秒 | Ctrl+C 退出[/]"

    return table

async def main():
    """异步主函数：执行监控流程"""
    console = Console()
    console.print("[bold yellow]🚀 正在初始化价格监控系统...[/]")

    # 1️⃣ 加载配置
    alert_config = load_alert_config()
    binance_conf = load_binance_config()
    
    # 获取刷新间隔
    refresh_interval = alert_config.get("display", {}).get("refresh_interval", 1)
    
    # 2️⃣ 初始化服务
    # PriceMonitorService 是业务核心，负责维护数据和判断报警
    service = PriceMonitorService(alert_config)
    
    # 提取需要监控的币种列表 (过滤掉 enabled: false 的)
    symbols = [s["symbol"] for s in alert_config.get("symbols", []) if s.get("enabled", True)]
    
    if not symbols:
        console.print("[bold red]❌ 未配置监控符号，请检查配置文件[/]")
        return

    # 3️⃣ 分离现货和合约符号
    # 策略：Binance 现货和合约是两个不同的 WebSocket 端点
    # 根据符号格式区分：BTC/USDT (现货) vs BTCUSDT (合约)
    spot_symbols = []
    futures_symbols = []
    
    for s in symbols:
        if "/" in s:
            spot_symbols.append(s)
        else:
            futures_symbols.append(s)

    # 4️⃣ 初始化 WebSocket 客户端
    # 我们可能需要创建 0~2 个 WebSocket 连接 (视配置而定)
    ws_clients = []
    
    # 4.1 现货 WebSocket
    if spot_symbols:
        console.print(f"🔌 [现货] 准备监控: {spot_symbols}")
        # 创建专用的现货配置 (禁用合约模式)
        spot_conf = create_market_config(binance_conf, is_futures=False)
        ws_spot = BinanceWebSocket(name="BinanceSpot", symbols=spot_symbols, config=spot_conf)
        
        # 🔗 关键连接点：将 Service 的 update 方法注册为 WebSocket 的回调
        # 当 WS 收到数据 -> 调用 service.on_ticker_update -> 更新内存状态
        ws_spot.add_callback(service.on_ticker_update)
        ws_clients.append(ws_spot)
        
    # 4.2 合约 WebSocket
    if futures_symbols:
        console.print(f"🔌 [合约] 准备监控: {futures_symbols}")
        # 创建专用的合约配置 (启用合约模式)
        futures_conf = create_market_config(binance_conf, is_futures=True)
        ws_futures = BinanceWebSocket(name="BinanceFutures", symbols=futures_symbols, config=futures_conf)
        
        # 🔗 同样注册回调，复用同一个 Service 实例处理所有数据
        ws_futures.add_callback(service.on_ticker_update)
        ws_clients.append(ws_futures)

    if not ws_clients:
        console.print("[bold red]❌ WebSocket 初始化失败[/]")
        return

    try:
        # 5️⃣ 启动连接
        # 异步启动所有 WS 连接
        console.print("[bold yellow]正在连接 WebSocket...[/]")
        for ws in ws_clients:
            await ws.connect()
            # 订阅 Ticker 数据流 (这是最轻量级的实时价格流)
            await ws.subscribe(ws.symbols, stream_type="ticker")
            
        console.print("[bold green]✅ 连接成功！启动实时界面...[/]")
        await asyncio.sleep(2) # ⏳ 等待 2秒 让数据预热，避免表格显示为空

        # 6️⃣ 启动 UI 循环
        # Live 组件：Rich 库提供的实时刷新容器
        # screen=True: 开启全屏模式
        # refresh_per_second=4: 界面重绘频率 (不影响数据接收频率)
        last_config_check = time.time()
        
        with Live(generate_table(service, alert_config), refresh_per_second=4, screen=True) as live:
            while True:
                # 🔄 伪热重载：每 5 秒检查一次配置文件
                # 💡 异步 I/O 优化：使用 run_in_executor 将文件读取放入线程池，避免阻塞主循环
                if time.time() - last_config_check > 5:
                    try:
                        # 🚀 性能关键：
                        # load_alert_config 是同步 IO 操作 (读硬盘)
                        # 直接调用会卡住 Event Loop，导致 WebSocket 心跳超时或数据积压
                        # run_in_executor(None, ...) 将其扔到线程池运行，await 等待结果，不阻塞主线程
                        loop = asyncio.get_running_loop()
                        new_config = await loop.run_in_executor(None, load_alert_config)
                        
                        if new_config:
                            # 1. 更新全局配置对象 (影响 generate_table 中的显示逻辑)
                            alert_config.update(new_config)
                            
                            # 2. 更新服务内部配置 (影响报警阈值判断)
                            service.update_config(new_config)
                            
                            # 3. 如果刷新频率变了，这里也能感知
                            refresh_interval = new_config.get("display", {}).get("refresh_interval", 1)
                    except Exception:
                        # 配置文件读取出错不要崩溃，继续用旧的
                        pass
                    last_config_check = time.time()

                # 🎨 每一帧重新生成表格对象
                # service 中保存了最新数据 (由 WS 回调在后台不断更新)
                live.update(generate_table(service, alert_config))
                
                # ⏳ 异步睡眠：让出 CPU 控制权给 Event Loop
                # 这段时间内，Python 去处理 WebSocket 的网络包
                await asyncio.sleep(refresh_interval)
                
    except KeyboardInterrupt:
        console.print("\n[yellow]正在停止监控...[/]")
    finally:
        for ws in ws_clients:
            await ws.disconnect()
        console.print("[green]监控已停止[/]")

def cli():
    """同步入口"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    cli()
