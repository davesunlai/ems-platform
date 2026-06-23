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
from ems.forecast import db as forecast_db
from ems.forecast.routes import router as forecast_router
from ems.pricing import db as pricing_db
from ems.pricing.routes import router as pricing_router
from ems.planner import db as planner_db
from ems.planner.routes import router as planner_router
from ems.market import db as market_db
from ems.market.routes import router as market_router
from ems.automation import db as automation_db
from ems.automation.routes import router as automation_router
from ems.ewelink.routes import router as ewelink_router
from ems.billing.routes import router as billing_router
from ems.contact.routes import router as contact_router
from ems.outputs.routes import router as outputs_router
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
        await control_db.ensure_queue_schema()
        await control_db.ensure_state_schema()
        await control_db.ensure_spot_rule_schema()
        await db.ensure_state_schema()
        await market_db.ensure_schema()
        await market_db.ensure_history_schema()
        await automation_db.ensure_schema()
        await localities_db.ensure_schema()
        await forecast_db.ensure_schema()
        await pricing_db.ensure_schema()
        await planner_db.ensure_schema()
        from ems.contact import db as contact_db
        await contact_db.ensure_schema()
        from ems.alerts import db as alerts_db
        await alerts_db.ensure_schema()
        from ems.outputs import db as outputs_db
        await outputs_db.ensure_schema()
        from ems.outages import db as outages_db
        await outages_db.ensure_schema()
        from ems.ewelink import store as ewelink_store
        await ewelink_store.ensure_schema()
    except Exception as exc:
        logger.error("Inicializace auth schématu selhala: %s", exc)
    yield
    await db.close_pool()


app = FastAPI(title="EMS Platform API", version="0.46.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(modules_router)
app.include_router(control_router)
app.include_router(forecast_router)
app.include_router(pricing_router)
app.include_router(planner_router)
app.include_router(market_router)
app.include_router(automation_router)
app.include_router(ewelink_router)
app.include_router(billing_router)
app.include_router(contact_router)
app.include_router(outputs_router)
app.include_router(localities_router)
from ems.outages.routes import router as outages_router
app.include_router(outages_router)
from ems.alerts.routes import router as alerts_router
app.include_router(alerts_router)

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
    return {"device_id": device_id, "metrics": metrics, "states": states, "active": bool(metrics)}


@app.get("/api/devices/aggregate-now")
async def devices_aggregate_now(ids: str, loc: int | None = None, _: dict = Depends(read)) -> dict:
    dev_ids = [x for x in ids.split(",") if x]
    out = await db.aggregate_now(dev_ids)
    if loc is not None:
        from ems.localities import db as loc_db
        from ems.billing import db as billing_db
        L = await loc_db.get(loc)
        if L:
            mode = L.get("pricing_mode") or "spot"
            out["pricing_mode"] = mode
            if mode == "tariff":
                ti, te = float(L.get("tariff_import_czk") or 0), float(L.get("tariff_export_czk") or 0)
                out["import_czk"] = round(out.get("import_kwh", 0) * ti, 2)
                out["export_czk"] = round(out.get("export_kwh", 0) * te, 2)
            else:
                c = await billing_db.today_spot_cost(dev_ids)
                out["import_czk"], out["export_czk"] = c["import_czk"], c["export_czk"]
    return out


@app.get("/api/devices/aggregate")
async def devices_aggregate(ids: str, metrics: str = "pv_power,load_power,grid_power",
                            minutes: int = 360, offset: int = 0, _: dict = Depends(read)) -> dict:
    minutes = max(360, min(minutes, 43200))
    offset = max(0, min(offset, 525600))
    dev_ids = [x for x in ids.split(",") if x]
    out = {}
    for met in [x for x in metrics.split(",") if x]:
        out[met] = await db.aggregate_history(dev_ids, met, minutes, offset)
    return {"minutes": minutes, "metrics": out}


@app.get("/api/devices/{device_id}/history")
async def device_history(device_id: str, metric: str, minutes: int = 360, offset: int = 0, _: dict = Depends(read)) -> dict:
    minutes = max(360, min(minutes, 43200))  # 6 h .. 30 dní
    offset = max(0, min(offset, 525600))      # až ~1 rok zpět
    points = await db.history(device_id, metric, minutes, offset)
    return {"device_id": device_id, "metric": metric, "points": points}
