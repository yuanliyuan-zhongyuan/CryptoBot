# CryptoTrade Learning Project

这是一个现代化的 Python 量化交易系统骨架，用于学习和演示量化策略（如网格、套利）的执行流程。

项目目前已升级为支持 **WebSocket 实时行情**，具备生产级的连接管理能力，能够同时接入现货与合约市场的真实数据。

---

## 🚀 核心特性

- **实时数据流**：基于 `websockets` 实现的高性能异步行情接入。
- **智能节点优选**：自动检测并选择延迟最低的交易所 WebSocket 节点。
- **多市场并行**：支持同时连接 Binance Spot（现货）和 Binance USDM（U本位合约）。
- **可扩展架构**：通过 `pyproject.toml` 管理依赖，支持模块化扩展。

---

## 🚀 快速开始

### 1. 环境准备
确保你的电脑已安装 Python 3.10 或更高版本。

```powershell
# 检查 Python 版本
python --version
```

### 2. 安装项目与依赖
本项目使用 `pyproject.toml` 管理依赖。请在项目根目录执行以下命令，将项目以**可编辑模式（Editable Mode）**安装，并启用异步支持：

```powershell
# 安装核心及异步依赖（注意后面的中括号）
pip install -e .[async]
```

> **说明**：
> - `-e` 模式意味着你修改本地代码后，无需重新安装即可生效。
> - `[async]` 选项会自动安装 `websockets` 等异步网络库。
> - 安装完成后，系统会自动注册一个 `cryptotrade-run` 的命令行工具。

### 3. 运行演示
直接在终端输入以下命令即可启动实时行情监控：

```powershell
cryptotrade-run
```

你将看到类似以下的真实市场数据推送：

```text
INFO [WS.binance-spot] ✅ 选中最佳节点: wss://stream.binance.com:443/ws (延迟 875.00ms)
INFO [cryptotrade.ticker] binance-spot BTC/USDT bid=91028.1900 ask=91028.2000
INFO [cryptotrade.ticker] binance-usdm BTC/USDT bid=90993.9000 ask=90994.0000
```

---

## ⚙️ 进阶用法

### 自定义运行参数
`cryptotrade-run` 支持多种参数，用于指定配置文件路径或运行时长。

```powershell
# 查看所有可用参数
cryptotrade-run --help

# 示例：运行 60 秒后自动优雅退出
cryptotrade-run --duration 60
```

### 核心参数说明
- `--cex-dir`: CEX 交易所配置目录（默认：`config/exchanges/cex`）
- `--dex-dir`: DEX 交易所配置目录（默认：`config/exchanges/dex`）
- `--strategy`: 策略配置文件路径（默认：`config/strategies/grid/basic_grid.yaml`）
- `--risk`: 风控配置文件路径（默认：`config/risk/risk.yaml`）

---

## 📦 项目结构

```text
d:\CryptoTrade\
├── config/                     # 配置文件（无需代码修改，直接配置 YAML）
│   ├── exchanges/              # 交易所连接参数 (Binance/OKX 等)
│   ├── strategies/             # 策略参数 (网格间距/套利阈值等)
│   └── risk/                   # 全局风控参数
├── core/                       # 核心架构层（系统骨架）
│   ├── adapters/               # 协议适配层：抹平不同交易所差异
│   │   ├── websocket_manager.py    # WebSocket 通用基类 (定义连接/心跳标准)
│   │   └── binance_adapter.py      # Binance 业务适配 (数据清洗/标准化)
│   └── coordinators/           # 业务协调层
│       └── trading_coordinator.py  # 系统大脑：分发行情、调度策略
├── exchanges/                  # 交易所底层驱动层
│   ├── cex/
│   │   └── binance/
│   │       └── websocket.py    # Binance 真实 WebSocket 客户端 (处理 Ping/Pong)
│   └── mock/                   # 模拟交易所 (用于回测/调试)
├── strategies/                 # 量化策略实现层
│   ├── grid/                   # 网格交易策略
│   └── arbitrage/              # 套利策略
├── pyproject.toml              # 项目依赖与构建配置
├── run.py                      # 程序启动入口
└── README.md                   # 项目说明书
```

---

## ⚠️ 注意事项

1. **网络连接**：
   由于接入的是真实交易所（Binance）的 WebSocket，请确保你的网络环境能够正常访问这些服务。

2. **配置文件路径**：
   项目已配置智能路径锚定。无论你在哪个目录下执行 `cryptotrade-run`，它都能自动找到项目内部的默认配置文件。

3. **私有配置（API Key）**：
   - 目前处于**行情只读模式**，无需 API Key。
   - 未来如果接入交易功能，**严禁**在版本控制（Git）中提交真实的 API Key。建议使用环境变量或在 `.gitignore` 排除的本地目录中存储私有配置。

---

## 🛠️ 开发指南

### 添加新依赖
如果需要引入新的库（例如 `httpx`），请修改 `pyproject.toml` 中的 `dependencies` 列表，然后再次执行：
```powershell
pip install -e .[async]
```

### 扩展交易所
参考 `core/adapters/binance_adapter.py`，实现新的 Adapter 类并注册到系统中，即可支持 OKX、Bybit 等其他交易所。
