# Integration Checklist v1

Use this checklist before the first long-running simulation deployment.

## 1. Prepare environment

Copy the production simulation template:

```powershell
Copy-Item .env.prod.sim.example .env
```

Then adjust:

- `DATABASE_URL`
- `FRONTEND_ORIGINS`
- `ONCHAIN_SIGNAL_SNAPSHOT_FILE`
- `ONCHAIN_RISK_SNAPSHOT_FILE`

## 2. Run preflight

```powershell
.\.venv\Scripts\python.exe scripts\release_preflight.py
```

Expected:

- `status` is `pass` or clearly understood `review`
- no unexpected missing snapshot warnings

## 3. Bootstrap database

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_db.py
```

## 4. Start local service

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 5. Run smoke check

```powershell
.\.venv\Scripts\python.exe scripts\runtime_smoke_check.py http://127.0.0.1:8000
```

Expected endpoints:

- `/health`
- `/health/ready`
- `/strategy-cards`
- `/strategy-cards/leaderboard`
- `/diagnostics/candidates`
- `/positions`
- `/positions/journal`

## 6. Run one manual scan

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/admin/scan?tier_mode=core-only"
```

Then check:

- `/positions/journal`
- `/diagnostics/candidates?tier_mode=core-only`

## 7. Review journal

Healthy early flow usually looks like:

- `trade_opened`
- `trade_confirmed`
- optional `trade_tp1_hit`
- optional `trade_tp2_hit`
- `trade_closed` or `trade_cancelled`

Unhealthy flow to investigate:

- repeated `trade_opened` and `trade_closed` on the same symbol
- repeated `trade_blocked` for the same reason
- `trade_loop_circuit_breaker`

## 8. First production posture

Recommended first long-running setting:

- `SIGNAL_STRATEGY_TIER_MODE=core-only`

Switch to `core+candidate` only after:

- no unexpected circuit breaker events
- no repeated same-symbol churn
- journal flow looks normal for several scans
