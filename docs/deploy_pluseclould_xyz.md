# Deploy to www.pluseclould.xyz

This project already serves the dashboard from the FastAPI app, so the simplest production setup is:

- `www.pluseclould.xyz` -> Caddy reverse proxy
- Caddy -> FastAPI container on port `8000`

## Files prepared

- `docker/Dockerfile`
- `docker/docker-compose.prod.yml`
- `docker/Caddyfile`

## DNS

Point these records to your public server:

- `A www.pluseclould.xyz -> <your_server_ipv4>`
- optional: `AAAA www.pluseclould.xyz -> <your_server_ipv6>`

## Server requirements

- Docker Engine
- Docker Compose plugin
- ports `80` and `443` open

## Environment

Create and fill `.env` in the project root. At minimum:

```env
ENV=prod
USE_SIMULATION=true
DATABASE_URL=sqlite:///./crypto_ai_trader.db
FRONTEND_ORIGINS=["https://www.pluseclould.xyz"]
ENABLE_ONCHAIN_SIGNAL_BOOST=true
ONCHAIN_SIGNAL_SNAPSHOT_FILE=data/onchainos/signals.snapshot.json
ONCHAIN_RISK_SNAPSHOT_FILE=data/onchainos/risks.snapshot.json
```

## Start

From the project root:

```powershell
docker compose -f docker/docker-compose.prod.yml up -d --build
```

## Verify

- `https://www.pluseclould.xyz/`
- `https://www.pluseclould.xyz/strategy-cards`
- `https://www.pluseclould.xyz/diagnostics/candidates?limit=10`
- `https://www.pluseclould.xyz/positions?include_closed=true`

## Notes

- Caddy will request TLS certificates automatically after DNS is pointed correctly.
- Because the frontend is served by the same FastAPI app, this setup avoids browser CORS issues.
- If the database file already exists from local runs, keep a backup before first production start.
