# Project Context

## Goal
`crypto-ai-trader` 是一个“模拟盘优先”的 AI 辅助加密交易系统。当前目标不是直接实盘自动下单，而是先把市场数据采集、候选筛选、策略判断、风控、模拟执行、记录和查询链路跑稳。

## Current Scope
- 以 Binance 行情作为默认市场数据来源。
- 保留 Coinglass 兼容入口，但当前仍以 Binance 为主。
- 支持 KOL 帖子导入、Twikit 抓取、策略卡生成和历史回测。
- 通过 FastAPI 提供健康检查、信号、持仓、管理类接口。
- 在真实交易权限未配置完成前，默认只跑模拟盘。

## Stack
- Python 3.11
- FastAPI
- SQLModel / SQLite
- APScheduler
- pytest
- 前端静态页：`frontend/strategy-card-dashboard/`

## Important Directories
- `app/main.py`: FastAPI 应用入口。
- `app/api/`: 对外 API 路由。
- `app/core/`: 调度、信号引擎、风控、模拟/实盘执行核心逻辑。
- `app/data/`: Binance、OKX、OnchainOS、Twikit 等数据接入层。
- `app/knowledge/`: KOL 导入、蒸馏、策略卡、回测相关逻辑。
- `app/storage/`: 数据模型、数据库和仓储层。
- `app/strategy/`: 规则策略模块。
- `scripts/`: 启动、回测、导入、检查、导出等脚本。
- `tests/`: 回归测试。
- `docs/`: 架构、运行、部署和专题说明。
- `frontend/strategy-card-dashboard/`: 策略卡展示页。
- `obsidian/`: KOL 笔记和策略卡 Markdown/JSON 资产。
- `data/`: 采集到的帖子、OnchainOS 快照和运行数据。

## Core Flow
```text
Market/KOL Data
-> Collector / Importer
-> Candidate selection
-> Strategy rules + Analyst scoring
-> RiskManager
-> Simulator / Live trader
-> Storage
-> API / Notification / Dashboard
```

## Key Commands
本地启动：
```powershell
pip install -r requirements.txt
python scripts/bootstrap_db.py
uvicorn app.main:app --reload
```

手动扫描：
```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/admin/scan
```

KOL 回测：
```powershell
.\.venv\Scripts\python.exe scripts/backtest_kol_cards.py
```

## Core Rules
- 默认以模拟盘为主，未确认前不要把改动朝“直接实盘执行”方向推进。
- API key、账号、密码等敏感信息只走环境变量或本地文件，不写进代码。
- 风控高于 AI 判断，最终交易放行由硬规则决定。
- 优先保留可测试性，改动核心逻辑时应同步关注 `tests/`。

## Working Style For New Threads
- 先读 `PROJECT_CONTEXT.md` 获取长期背景。
- 再读 `WORKLOG.md` 了解最近状态。
- 最后只按 `NEXT_TASK.md` 处理当前任务，避免在一个线程里同时推进多个目标。
