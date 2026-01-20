# CryptoTrade 学习项目

这是一个用于学习和研究加密货币交易策略的最小化可运行项目。系统基于 CEX/DEX 配置进行多交易所行情模拟，并通过 Coordinator/Runner/Engine 架构协调执行策略。

目前默认演示「网格监控」策略，支持通过配置文件切换为套利等其他策略。

## ✨ 功能特性

- **多交易所模拟**: 支持 CEX (Binance, OKX, Backpack) 和 DEX (Hyperliquid, Paradex 等) 的配置与模拟。
- **核心架构**: 
  - `TradingCoordinator`: 交易协调器，负责加载配置和管理生命周期。
  - `Runner`: 策略运行器，负责策略的具体调度。
  - `Engine`: 策略引擎，执行具体的交易逻辑。
- **默认策略**: 基础网格 (Basic Grid)
  - 目前配置为 `monitor_only: true` (仅监控)，用于观察价差和网格触发情况。
- **配置化驱动**: 所有策略参数、交易所设置、风控规则均通过 YAML 文件管理。

## 📂 项目结构

```text
CryptoBot/
├── config/                 # 配置文件目录
│   ├── exchanges/          # 交易所配置 (CEX/DEX)
│   ├── risk/               # 风控配置 (如最大持仓限制)
│   └── strategies/         # 策略配置 (如网格参数)
├── core/                   # 核心逻辑 (Exchange, Coordinator)
├── strategies/             # 策略实现代码 (Arbitrage, Grid)
├── run.py                  # 项目启动入口
├── requirements.txt        # 依赖列表
└── pyproject.toml          # 项目打包配置
```

## 🚀 快速开始

### 1. 安装依赖

请确保你的 Python 版本 >= 3.10。在项目根目录下运行：

```bash
# 以开发模式安装当前项目
pip install -e .
```

> **注意**: 这是一个学习项目，建议在虚拟环境中运行。

### 2. 运行项目

项目提供了两种运行方式，你可以指定运行持续时间（单位：秒），方便观察输出。

**方式一：使用命令行工具 (Console Script)**

```bash
# 运行 10 秒后自动退出
cryptotrade-run --duration 10
```

**方式二：以模块方式运行**

```bash
# 运行 20 秒
python -m cryptotrade.run --duration 20
```

### 3. 查看输出

程序启动后会加载配置并在控制台输出实时监控信息。

**示例输出**：

```bash
(MyBot) bugbug@CryptoMacBook CryptoBot % cryptotrade-run --duration 10
BTC-USDC-PERP mode=Monitor change=NA
BTC-USDC-PERP segments=0/6 initial=1.0000% step=0.5000%
ETH-USDC-PERP mode=Monitor change=NA
ETH-USDC-PERP segments=0/6 initial=1.0000% step=0.5000%
BTC-USDC-PERP mode=Monitor change=0.0000% base@binance
BTC-USDC-PERP segments=0/6 initial=1.0000% step=0.5000%
```

输出说明：
- `mode=Monitor`: 当前策略处于仅监控模式。
- `segments=0/6`: 当前触发的网格段数（0表示未触发）。
- `change=...`: 价格变化率或价差信息。

## ⚙️ 配置说明

你可以在 `config/` 目录下修改 YAML 文件来调整行为：

- **策略配置**: `config/strategies/grid/basic_grid.yaml`
  - 修改 `initial_spread_threshold` 调整触发阈值。
  - 修改 `symbols` 添加或减少监控的交易对。
- **交易所配置**: `config/exchanges/`
  - 在 `cex/` 或 `dex/` 中添加或修改交易所参数。
- **运行时参数**:
  - `cryptotrade-run` 支持 `--cex-dir`, `--dex-dir`, `--strategy`, `--risk` 等参数来指定不同的配置文件路径。

## 🛠️ 开发指南

- **添加新策略**: 在 `strategies/` 下创建新的策略包，并在 `core/trading_coordinator.py` 中注册对应的 Runner。
- **扩展交易所**: 在 `config/exchanges/` 添加新的 YAML 配置。


