from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    routes_account,
    routes_admin,
    routes_diagnostics,
    routes_health,
    routes_positions,
    routes_signals,
    routes_strategy_cards,
)
from app.config import get_settings
from app.core.scheduler import build_scheduler
from app.logging_config import configure_logging
from app.storage.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    settings = get_settings()
    scheduler = build_scheduler(settings)
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Crypto AI Trader", version="0.1.0", lifespan=lifespan)

settings = get_settings()
frontend_origins = [
    origin.strip()
    for origin in (settings.frontend_origins if hasattr(settings, "frontend_origins") else [])
    if origin.strip()
]
if frontend_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=frontend_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(routes_health.router)
app.include_router(routes_account.router)
app.include_router(routes_diagnostics.router)
app.include_router(routes_signals.router)
app.include_router(routes_positions.router)
app.include_router(routes_admin.router)
app.include_router(routes_strategy_cards.router)

frontend_dir = Path(__file__).resolve().parents[1] / "frontend" / "strategy-card-dashboard"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dir), name="assets")


@app.get("/", include_in_schema=False)
def dashboard_index():
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "frontend_not_configured"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    favicon_file = frontend_dir / "favicon.svg"
    if favicon_file.exists():
        return FileResponse(favicon_file, media_type="image/svg+xml")
    return {"status": "favicon_not_configured"}
