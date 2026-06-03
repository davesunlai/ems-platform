"""REST API nad uloženou telemetrií + autentizace a RBAC."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ems.auth import db as auth_db
from ems.auth.deps import require_permission
from ems.auth.routes import router as auth_router
from ems.modules import db as modules_db
from ems.modules.routes import router as modules_router
from ems.control import db as control_db
from ems.control.routes import router as control_router
from ems.market import db as market_db
from ems.market.routes import router as market_router
from ems.automation import db as automation_db
from ems.automation.routes import router as automation_router
from ems.localities import db as localities_db
from ems.localities.routes import router as localities_router
from . import db

logger = logging.getLogger("ems.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Idempotentně připrav schéma uživatelů a založ admina, pokud chybí.
    try:
        await auth_db.ensure_schema()
        await auth_db.seed_admin()
        await modules_db.ensure_schema()
        await control_db.ensure_schema()
        await db.ensure_state_schema()
        await market_db.ensure_schema()
        await automation_db.ensure_schema()
        await localities_db.ensure_schema()
    except Exception as exc:
        logger.error("Inicializace auth schématu selhala: %s", exc)
    yield
    await db.close_pool()


app = FastAPI(title="EMS Platform API", version="0.7.3", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(modules_router)
app.include_router(control_router)
app.include_router(market_router)
app.include_router(automation_router)
app.include_router(localities_router)

# Telemetrie vyžaduje oprávnění "read".
read = require_permission("read")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/devices")
async def devices(_: dict = Depends(read)) -> list[dict]:
    return await db.list_devices()


@app.get("/api/devices/{device_id}/latest")
async def latest(device_id: str, _: dict = Depends(read)) -> dict:
    rows = await db.latest_for_device(device_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Zařízení nemá data")
    metrics = {
        r["metric"]: {
            "value": r["value"],
            "unit": r["unit"],
            "quality": r["quality"],
            "time": r["time"].isoformat(),
        }
        for r in rows
    }
    states = await db.latest_states(device_id)
    return {"device_id": device_id, "metrics": metrics, "states": states}


@app.get("/api/devices/{device_id}/history")
async def device_history(device_id: str, metric: str, minutes: int = 360, _: dict = Depends(read)) -> dict:
    minutes = max(360, min(minutes, 43200))  # 6 h .. 30 dní
    points = await db.history(device_id, metric, minutes)
    return {"device_id": device_id, "metric": metric, "points": points}
