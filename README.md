# CryptoTrade Learning Project

这是一个现代化的 Python 量化交易系统骨架，用于学习和演示量化策略（如网格、套利）的执行流程。

项目目前已升级为支持 **WebSocket 实时行情** 和 **REST API 交互**，具备生产级的连接管理能力，能够同时接入现货与合约市场的真实数据。

---

## 🚀 核心特性

- **终端交互面板**：基于 `Textual/Rich` 构建的现代化 TUI (Terminal UI)，提供实时行情看板与策略状态监控。
- **实时数据流**：基于 `websockets` 实现的高性能异步行情接入，支持多流并发。
- **智能节点优选**：自动检测并选择延迟最低的交易所 WebSocket 节点。
- **多市场并行**：支持同时连接 Binance Spot（现货）和 Binance USDM（U本位合约）。
- **REST API 集成**：内置 `aiohttp` 异步客户端，支持账户查询、挂单管理及历史数据获取。
- **可扩展架构**：基于 `pyproject.toml` 的现代化包管理，模块化拆分策略、驱动与核心服务。

---

## 🚀 快速开始

### 1. 环境准备
确保你的电脑已安装 Python 3.10 或更高版本。

```powershell
# 检查 Python 版本
python --version
```

### 2. 安装项目与依赖
本项目使用 `pyproject.toml` 管理依赖。请在项目根目录执行以下命令，将项目以**可编辑模式（Editable Mode）**安装，并启用异步与 CLI 支持：

```powershell
# 安装核心、异步及 CLI 界面依赖
pip install -e .[async,cli]
```

> **说明**：
> - `-e` 模式意味着你修改本地代码后，无需重新安装即可生效。
> - `[async,cli]` 选项会自动安装 `websockets`、`aiohttp` (异步) 以及 `rich` (终端界面)。
> - 安装完成后，系统会自动注册 `cryptotrade-run`、`cryptotrade-rest`、`cryptotrade-monitor` 和 `cryptotrade-scanner` 命令行工具。

### 3. 运行演示

#### 方式 A: 实时行情看板 (Monitor)
启动全屏终端监控面板，实时查看多币种行情与波动率：

```powershell
cryptotrade-monitor
```

#### 方式 B: 全市场雷达扫描 (Scanner)
启动全币种雷达，自动发现高波动与大成交量机会（Spot/Futures 双轨扫描）：

```powershell
cryptotrade-scanner
```

#### 方式 C：策略运行 (Strategy Run)
直接在终端输入以下命令启动策略协调器（带日志流）：

```powershell
cryptotrade-run
```

你将看到类似以下的真实市场数据推送：

```text
INFO [WS.binance-spot] ✅ 选中最佳节点: wss://stream.binance.com:443/ws (延迟 875.00ms)
INFO [cryptotrade.ticker] binance-spot BTC/USDT bid=91028.1900 ask=91028.2000
```

#### 方式 B：API 功能测试 (REST)
用于测试 API 连通性、账户余额及持仓查询：

```powershell
cryptotrade-rest
```

输出示例：
```text
INFO - ✅ [Binance REST] API Key 已配置
INFO - 💰 [3/5] 测试私有接口: 获取账户余额...
INFO -    - USDT (Futures): 可用=16.2444, 冻结=11.6328
```

---

## 🔍 实时监控与数据流配置

为了满足不同的监控需求（如高频套利 vs 趋势看板），系统支持多种 WebSocket 数据流模式。

### 支持的流类型 (`stream_type`)
基于 `BinanceStreamType` 常量定义：
- **`bookTicker`** (默认): 仅推送最优买卖价 (Best Bid/Ask)。数据量极小，延迟最低，适合**高频网格**。
- **`ticker`** (即 `TICKER_24H`): 推送 24小时统计数据（最新价、涨跌幅、成交量）。适合**行情仪表盘**。
- **`trade`**: 实时成交流。
- **`userData`**: 账户订单与余额变动更新。

### 开发调用示例
在编写自定义监控脚本时，可通过 `stream_type` 参数灵活切换：

```python
from cryptotrade.exchanges.cex.binance.base import BinanceBase

# 场景 A: 高频策略 (默认)
# 获取 bid/ask 价格，毫秒级响应
await ws_client.subscribe(["BTCUSDT"])

# 场景 B: 市场趋势监控
# 获取 24小时涨跌幅、成交量等统计数据
await ws_client.subscribe(
    ["BTCUSDT", "ETHUSDT"], 
    stream_type=BinanceBase.BinanceStreamType.TICKER_24H
)
```

---

## ⚙️ 进阶用法

### 真实交易 vs 模拟回测
系统根据配置文件自动决定连接真实交易所还是使用 Mock 数据。

1. **启用真实交易 (Binance)**:
   - 修改 `config/exchanges/cex/binance.yaml`
   - 设置 `markets.spot.enabled: true` 或 `markets.USD-M Futures.enabled: true`
   - 系统会自动加载 `BinanceAdapter` 并连接真实 WebSocket。

2. **使用模拟数据 (Mock)**:
   - 确保 `binance.yaml` 中所有 markets 均为 `false`。
   - 系统会自动回退到 `MockExchange`，生成随机漫步价格数据（无需联网）。

### 核心参数说明
`cryptotrade-run` 支持多种参数：
- `--cex-dir`: CEX 交易所配置目录（默认：`config/exchanges/cex`）
- `--strategy`: 策略配置文件路径（默认：`config/strategies/grid/basic_grid.yaml`）
- `--duration`: 运行时长（秒），例如 `--duration 60`。设为 `-1` 则无限运行（适合监控模式）。

---

## 📦 项目结构

```text
d:\CryptoTrade\
├── config/                     # 配置文件（无需代码修改，直接配置 YAML）
│   ├── alert/                  # 告警与通知配置
│   ├── scanner/                # 扫描器配置 (Binance Scanner)
│   ├── exchanges/              # 交易所连接参数
│   │   ├── cex/                # CEX 配置 (Binance, OKX, Backpack)
│   │   └── dex/                # DEX 配置 (Hyperliquid, dYdX 等)
│   ├── strategies/             # 策略参数 (网格间距/套利阈值等)
│   └── risk/                   # 全局风控参数
├── core/                       # 核心架构层（系统骨架）
│   ├── adapters/               # 协议适配层：抹平不同交易所差异
│   │   ├── websocket_manager.py    # WebSocket 通用基类
│   │   ├── subscription_manager.py # 订阅管理器 (管理动态订阅)
│   │   ├── binance_adapter.py      # Binance 业务适配 (混合 WS/REST)
│   │   └── models.py               # 统一数据模型 (Ticker/Order/Position)
│   ├── coordinators/           # 业务协调层
│   │   └── trading_coordinator.py  # 系统大脑：分发行情、调度策略
│   └── services/               # 通用基础服务
│       ├── monitor.py              # 监控服务模块 (Monitor)
│       └── scanner.py              # 雷达扫描模块 (Scanner)
├── exchanges/                  # 交易所底层驱动层
│   ├── cex/
│   │   └── binance/            # Binance 驱动 (REST/WS/Base)
│   ├── dex/                    # DEX 驱动预留目录
│   └── mock/                   # 模拟交易所 (用于回测/调试)
├── strategies/                 # 策略逻辑实现层
│   ├── grid/                   # 网格策略 (Engine/Runner)
│   └── arbitrage/              # 套利策略 (Engine/Runner)
├── pyproject.toml              # 项目依赖与构建配置
├── run.py                      # 策略运行入口 (cryptotrade-run)
├── run_rest.py                 # REST 测试入口 (cryptotrade-rest)
├── run_monitor.py              # 监控看板入口 (cryptotrade-monitor)
├── run_scanner.py              # 雷达扫描入口 (cryptotrade-scanner)
└── README.md                   # 项目说明书
```

---

## ❓ FQA常见问题 (Troubleshooting)

### Q1: `ModuleNotFoundError: No module named 'cryptotrade'`
**原因**：未正确安装项目包，或者在非项目根目录运行。
**解决**：
1. 确保在 `d:\CryptoTrade` 目录下。
2. 执行 `pip install -e .[async]` 重新注册包。
3. 如果仍报错，可以直接使用 Python 运行脚本（已内置路径回退支持）：
   ```powershell
   python run.py
   # 或
   python run_rest.py
   ```

### Q2: WebSocket 连接超时 / 无法连接
**原因**：国内网络环境无法直接访问 Binance API。
**解决**：
- 确保使用了全局代理或 VPN。
- 检查 `config/exchanges/cex/binance.yaml` 中的 `ws_base_urls` 配置，尝试更换节点。

---

## ⚠️ 注意事项

1. **配置文件路径**：
   项目已配置智能路径锚定。无论你在哪个目录下执行命令，它都能自动找到项目内部的默认配置文件。

2. **私有配置（API Key）**：
   - 目前处于**行情只读模式**，无需 API Key 即可获取 Public Data。
   - 若需测试账户接口，请在 `binance.yaml` 中填入 Key，但**严禁**提交到 Git。建议使用环境变量。

---

## 🛠️ 开发指南

### 添加新依赖
如果需要引入新的库，请修改 `pyproject.toml` 中的 `dependencies` 列表，然后再次执行：
```powershell
pip install -e .[async]
```

### 扩展交易所
参考 `core/adapters/binance_adapter.py`，实现新的 Adapter 类并注册到 `TradingCoordinator` 中，即可支持 OKX、Bybit 等其他交易所。
