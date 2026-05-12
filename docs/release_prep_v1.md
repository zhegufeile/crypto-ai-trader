# Release Prep v1

This checklist is for the simulation-first production release of the project.

## Goal

Bring the system to a stable long-running simulation deployment before any real exchange execution is enabled.

## Required checks

1. Environment
- `ENV=prod`
- `USE_SIMULATION=true`
- `DATABASE_URL` points to the intended production file or database
- `SIGNAL_STRATEGY_TIER_MODE` is set intentionally:
  - `core-only` for the most conservative mode
  - `core+candidate` for the default balanced mode

2. Onchain files
- `ONCHAIN_SIGNAL_SNAPSHOT_FILE` exists if onchain boost is enabled
- `ONCHAIN_RISK_SNAPSHOT_FILE` exists if token risk downgrade is enabled

3. Risk guardrails
- `MAX_OPEN_POSITIONS`
- `MAX_SAME_DIRECTION_POSITIONS`
- `MAX_SAME_STRUCTURE_POSITIONS`
- `MAX_CONSECUTIVE_LOSSES`
- `SYMBOL_COOLDOWN_MINUTES`
- `TRADE_ACTION_CIRCUIT_WINDOW_MINUTES`
- `MAX_TRADE_ACTIONS_IN_WINDOW`

4. API health
- `GET /health`
- `GET /health/ready`
- `GET /diagnostics/candidates`
- `GET /positions`
- `GET /positions/journal`

## Preflight command

Run before deployment:

```powershell
.\.venv\Scripts\python.exe scripts\release_preflight.py
```

## Recommended production sequence

1. Initialize database

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_db.py
```

2. Run one manual scan

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/admin/scan
```

3. Verify:
- no unexpected rapid trade loop events in `/positions/journal`
- no repeated block reasons for the same symbol
- diagnostics look sensible under the chosen `tier_mode`

4. Start the service / scheduler

## Release decision

Safe to proceed when:
- health endpoint is clean
- readiness warnings are understood
- manual scan succeeds
- journal shows normal open / confirm / manage / close flow
- no circuit breaker fires unexpectedly
