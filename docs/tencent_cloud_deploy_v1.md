# Tencent Cloud Deploy v1

This guide is for the simulation-first deployment to Tencent Cloud using:

- domain: `https://www.pluseclould.xyz`
- server IP: `43.157.224.147`
- reverse proxy: Caddy
- app runtime: Docker Compose

## 1. DNS

In Tencent Cloud DNS, make sure:

- `A www.pluseclould.xyz -> 43.157.224.147`

Wait until the record resolves to the server before starting Caddy.

## 2. Server requirements

Install and verify:

- Docker Engine
- Docker Compose plugin

Open these ports in Tencent Cloud security group:

- `22`
- `80`
- `443`

## 3. Upload project

Place the repo under `agentuser`, and keep `ubuntu` only as the SSH entry user if needed:

```bash
sudo -iu agentuser
cd /home/agentuser
git clone <your-repo-url> crypto-ai-trader
cd /home/agentuser/crypto-ai-trader
```

If you are not using Git on the server, upload the full project directory instead.

Recommended ownership baseline:

```bash
sudo chown -R agentuser:agentuser /home/agentuser/crypto-ai-trader
```

## 4. Create production env

Use the prepared Tencent Cloud template:

```bash
cp .env.tencent.prod.example .env
```

Recommended first-run settings:

- `SIGNAL_STRATEGY_TIER_MODE=core-only`
- keep `USE_SIMULATION=true`
- keep `BINANCE_PROXY_URL=` empty unless the server cannot reach Binance directly

Then fill:

- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` if you want alerts
- any future paid API keys

For non-root app containers, keep these aligned with the host `agentuser` account on the server:

```bash
id agentuser
```

Then set:

- `APP_UID=<agentuser uid>`
- `APP_GID=<agentuser gid>`

The current default template assumes `APP_UID=1001` and `APP_GID=1002`.

## 5. Prepare onchain data

The app now mounts `data/` into the container, so snapshots generated on the server will persist.

Before first launch, ensure these exist:

- `data/onchainos/signals.snapshot.json`
- `data/onchainos/risks.snapshot.json`

If `signals.snapshot.json` exists but `risks.snapshot.json` is missing, log into `onchainos` on the server and run:

```bash
python scripts/refresh_onchainos_risks.py
```

If the server needs a proxy for OnchainOS:

```bash
python scripts/refresh_onchainos_risks.py --proxy http://127.0.0.1:10809
```

## 6. Preflight

Run:

```bash
python scripts/release_preflight.py
```

Expected:

- `status` is `pass`
- or `review` only for warnings you intentionally accept

## 7. Start containers

```bash
sudo -iu agentuser
cd /home/agentuser/crypto-ai-trader
docker compose -f docker/docker-compose.prod.yml up -d --build
```

## 8. Verify after boot

Check container status:

```bash
docker compose -f docker/docker-compose.prod.yml ps
```

Check logs:

```bash
docker compose -f docker/docker-compose.prod.yml logs --tail=100 trader
docker compose -f docker/docker-compose.prod.yml logs --tail=100 caddy
```

Confirm the app container is no longer running as root:

```bash
docker compose -f docker/docker-compose.prod.yml exec trader id
```

Expected: the reported uid/gid should match `APP_UID` / `APP_GID`, not `0(root)`.

Verify endpoints:

- `https://www.pluseclould.xyz/`
- `https://www.pluseclould.xyz/health`
- `https://www.pluseclould.xyz/health/ready`

`/health/ready` should show:

- `status: ready`
- `scheduler_running: true`
- `warnings: []`

## 9. First live simulation check

Run one scan:

```bash
curl -X POST "https://www.pluseclould.xyz/admin/scan?tier_mode=core-only"
```

Then inspect:

- `https://www.pluseclould.xyz/diagnostics/candidates?tier_mode=core-only&limit=5`
- `https://www.pluseclould.xyz/positions`
- `https://www.pluseclould.xyz/positions/journal?limit=20`

## 10. Recommended first-week posture

Keep:

- `USE_SIMULATION=true`
- `SIGNAL_STRATEGY_TIER_MODE=core-only`

Switch to `core+candidate` only after journal flow looks stable for multiple scans and there are no unexpected circuit breaker events.
