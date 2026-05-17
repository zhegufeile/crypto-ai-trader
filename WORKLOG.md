# Worklog

## Current Status
- 项目已具备 MVP 基础链路：数据采集、候选筛选、风控、模拟执行、API 查询。
- 仓库中已经接入 KOL/Twikit/OnchainOS 相关数据流程，并配有较完整测试集。
- 当前工作区不是干净状态，已有一批正在进行中的本地改动。

## Active Areas Seen In Workspace
- `app/api/routes_account.py`
- `app/api/routes_positions.py`
- `app/core/live_trader.py`
- `app/core/scheduler.py`
- `app/core/signal_engine.py`
- `app/storage/repositories.py`
- `frontend/strategy-card-dashboard/app.js`
- 多个对应测试文件

## Notes About Current Git Status
- 有若干 `.tmp_test/pytest-of-ang81/...` 下的已删除测试临时文件记录。
- 上面这些删除项看起来像测试运行后的临时目录残留，不适合作为长期上下文的一部分。
- 后续处理任务前，先确认这些改动是否需要保留，避免误判。

## Known Documentation Sources
- `README.md`: MVP 范围和常用命令。
- `docs/architecture.md`: 总体数据流。
- `docs/runbook.md`: 本地运行和风控原则。

## Suggested Update Rule
每完成一轮工作后，只更新这几项：
- 做了什么
- 改了哪些关键文件
- 还剩什么 blocker
- 下一步最具体的动作是什么

## Last Refresh
- 由 Codex 于 2026-05-16 基于仓库当前结构初始化。
