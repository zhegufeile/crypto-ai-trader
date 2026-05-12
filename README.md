# Crypto AI Trader MVP

一个“模拟盘优先”的虚拟币 AI 辅助交易系统。第一版默认使用 Binance Futures 行情数据，保留 Coinglass 适配入口，先完成候选筛选、结构判断、风控、模拟开仓、记录与 API 查询。

## MVP 范围

- Binance 行情采集：24h ticker、资金费率、OI、多空比、主动买卖比。
- Coinglass 兼容入口：`CoinglassClient` 方法名保留，默认内部走 Binance。
- 候选币筛选：流动性、涨跌幅、BTC 背景、资金费率等硬指标。
- AI 分析占位：无 LLM key 时使用可解释规则分析，输出结构、方向、置信度、盈亏比、止损止盈。
- 风控：置信度、盈亏比、最大持仓数、单日亏损、黑名单、流动性、资金费率过热。
- 模拟盘：通过信号生成模拟交易记录，暂不实盘下单。
- KOL 导入与统计：原始帖子入库后，可回测并回填策略卡的历史胜率、平均 RR 和样本数。
- FastAPI：健康检查、信号查询、持仓查询、手动扫描。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/bootstrap_db.py
uvicorn app.main:app --reload
```

手动触发一次扫描：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/admin/scan
```

导入 KOL 原始帖子并生成策略卡：

```powershell
.\.venv\Scripts\python.exe scripts/import_kol_posts.py alpha posts.json --creator xincctnnq --format md
```

用 Twikit 抓取某个 KOL 的最近推文，并导出为流水线可直接使用的 JSON/CSV：

```powershell
.\.venv\Scripts\python.exe scripts/twikit_fetch_user_tweets.py Arya_web3 --max-tweets 3000
```

首次运行会使用 `--username` / `--password` 或环境变量 `X_USERNAME` / `X_PASSWORD` 登录，并把 cookies 保存到 `data/twikit/cookies.json`，后续会复用。

回测并更新策略卡统计：

```powershell
.\.venv\Scripts\python.exe scripts/backtest_kol_cards.py
```

批量处理多个 KOL 导出文件，并为每个 KOL 生成 Obsidian 笔记：

```powershell
.\.venv\Scripts\python.exe scripts/batch_kol_classify.py data/arya data/btc_alert data/thecryptoskanda data/derrrrrq data/cryptorounder data/lanaaielsa --persist
```

默认会输出 `kol_batch_report.json`，并把每个 KOL 的 Markdown 笔记写入 `obsidian/kol_notes/`。

## 重要配置

- `MARKET_DATA_SOURCE=binance`：默认使用 Binance。
- `MARKET_DATA_SOURCE=coinglass`：保留入口，目前返回 not_configured 占位结果。
- `USE_SIMULATION=true`：第一版只做模拟盘。
- `CONFIDENCE_THRESHOLD=0.70`：低于该置信度不生成可执行信号。
- `MIN_RR=2.0`：低于该盈亏比不通过风控。

## 后续路线

1. 保存行情快照与回测结果，校准盈亏比和胜率。
2. 接入真实 KOL 数据源，把推文蒸馏成策略卡。
3. 接入 LLM，只让它做结构解释和置信度辅助，不直接拍板下单。
4. 模拟盘稳定后，再接交易所下单接口，并保持小仓位和熔断。
