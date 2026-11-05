"""API 🚘 Auta: účty (admin), vozidla, stav (read)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db, service

router = APIRouter(prefix="/api/cars", tags=["cars"])
read = require_permission("read")
admin = require_permission("admin")


class AccountIn(BaseModel):
    client_id: str
    locality_id: int | None = None


class VehiclePatch(BaseModel):
    name: str | None = None
    locality_id: int | None = None
    wallbox_module_id: str | None = None
    capacity_kwh: float | None = None
    key_map: dict | None = None
    enabled: bool | None = None


def _acc_public(a: dict) -> dict:
    keep = ("id", "locality_id", "client_id", "gcid", "status", "last_error", "user_code", "verification_uri",
            "device_expires_at", "access_expires_at", "refresh_expires_at", "stream_status", "stream_since",
            "stream_msgs", "rest_calls_today", "rest_day", "container_id", "created_at")
    d = {k: a.get(k) for k in keep}
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


@router.get("/accounts")
async def accounts(_: dict = Depends(admin)):
    return [_acc_public(a) for a in await db.list_accounts()]


@router.post("/accounts")
async def create_account(body: AccountIn, _: dict = Depends(admin)):
    a = await db.create_account(body.locality_id, body.client_id)
    return _acc_public(a)


@router.delete("/accounts/{aid}")
async def delete_account(aid: int, _: dict = Depends(admin)):
    await db.delete_account(aid)
    return {"ok": True}


@router.post("/accounts/{aid}/connect")
async def connect(aid: int, _: dict = Depends(admin)):
    try:
        return await service.start_device_flow(aid)
    except service.CarDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/accounts/{aid}/poll")
async def poll(aid: int, _: dict = Depends(admin)):
    return await service.poll_device_flow(aid)


@router.post("/accounts/{aid}/sync")
async def sync(aid: int, _: dict = Depends(admin)):
    try:
        return await service.sync_vehicles(aid)
    except service.CarDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/vehicles")
async def vehicles(locality_id: int | None = None, _: dict = Depends(read)):
    out = []
    for v in await db.list_vehicles(locality_id):
        st = await db.state(v["vin"])
        cv = service.car_view(v, st)
        cv["km_today"] = None
        if isinstance(cv.get("odometer_km"), (int, float)):
            base = await db.odometer_at_day_start(v["vin"], cv["key_map_odometer"])
            cv["km_today"] = round(max(0.0, float(cv["odometer_km"]) - base), 1) if base is not None else None
        out.append({**cv, "enabled": v.get("enabled", True), "key_map": {**db.DEFAULT_KEY_MAP, **(v.get("key_map") or {})}})
    return out


@router.patch("/vehicles/{vin}")
async def patch_vehicle(vin: str, body: VehiclePatch, _: dict = Depends(admin)):
    await db.update_vehicle(vin, body.model_dump(exclude_unset=True))
    return {"ok": True}


@router.get("/vehicles/{vin}/state")
async def vehicle_state(vin: str, _: dict = Depends(read)):
    """Všechny přijaté deskriptory (pro mapování rolí a diagnostiku)."""
    return await db.state(vin)


@router.get("/vehicles/{vin}/history")
async def vehicle_history(vin: str, key: str, hours: int = 48, _: dict = Depends(read)):
    return await db.history(vin, key, max(1, min(hours, 24 * 31)))


@router.get("/sessions")
async def sessions(locality_id: int | None = None, date: str | None = None, month: str | None = None, _: dict = Depends(read)):
    """Relace nabíjení aut (odvozené z CarData) za den (date=YYYY-MM-DD) nebo měsíc (month=YYYY-MM), s GPS polohou."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Prague")
    try:
        if date:
            y, m, d = (int(x) for x in date.split("-")[:3]); s = datetime(y, m, d, tzinfo=tz); e = s + timedelta(days=1)
        elif month:
            y, m = (int(x) for x in month.split("-")[:2]); s = datetime(y, m, 1, tzinfo=tz)
            e = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=tz)
        else:
            e = datetime.now(tz); s = e - timedelta(days=31)
    except Exception:
        raise HTTPException(status_code=400, detail="date=YYYY-MM-DD nebo month=YYYY-MM")
    out = []
    for v in await db.list_vehicles(locality_id):
        if v.get("enabled", True):
            out.extend(await db.car_sessions(v, s, e))
    out.sort(key=lambda r: r["start"])
    # místo nabíjení (obec + provozovatel) z OSM — cache, max 3 nové dotazy na požadavek
    try:
        from . import geo
        info = await geo.resolve_many([(r["lat"], r["lon"]) for r in out if r.get("lat") is not None], max_new=3)
        for r in out:
            if r.get("lat") is not None:
                g = info.get((round(float(r["lat"]), 4), round(float(r["lon"]), 4)))
                r["place"] = (g or {}).get("place"); r["operator"] = (g or {}).get("operator")
                r["station_name"] = (g or {}).get("station_name"); r["place_label"] = geo.label(g); r["place_pending"] = bool((g or {}).get("pending")) or g is None
    except Exception as exc:
        import logging; logging.getLogger("ems.cars").info("geo: %s", exc)
    return out


@router.get("/month")
async def month_stats(month: str, locality_id: int | None = None, _: dict = Depends(read)):
    """Za měsíc (YYYY-MM) pro každé auto: nabito kWh (wallbox / jinde), ujeto km, kWh/100 km."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Prague")
    try:
        y, m = (int(x) for x in month.split("-")[:2]); s = datetime(y, m, 1, tzinfo=tz); e = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=tz)
    except Exception:
        raise HTTPException(status_code=400, detail="month=YYYY-MM")
    return [await db.month_stats(v, s, e) for v in await db.list_vehicles(locality_id) if v.get("enabled", True)]


@router.get("/geo-settings")
async def geo_settings_get(_: dict = Depends(admin)):
    from ems.api.db import get_setting
    key = await get_setting("ocm_api_key", None)
    return {"ocm_api_key_set": bool(key), "ocm_api_key_hint": (key[:4] + "…" + key[-4:]) if key and len(key) > 10 else None}


class GeoSettingsIn(BaseModel):
    ocm_api_key: str | None = None


@router.put("/geo-settings")
async def geo_settings_put(body: GeoSettingsIn, _: dict = Depends(admin)):
    from ems.api.db import set_setting
    await set_setting("ocm_api_key", (body.ocm_api_key or "").strip() or None)
    return {"ok": True}


class PlaceIn(BaseModel):
    lat: float
    lon: float
    operator: str | None = None
    name: str | None = None
    place: str | None = None
    radius_m: float = 150


@router.get("/geo-places")
async def geo_places(_: dict = Depends(read)):
    from . import geo
    return await geo.user_places()


@router.post("/geo-places")
async def geo_place_add(body: PlaceIn, user: dict = Depends(admin)):
    """Ručně pojmenovat nabíječku (operátor, název) — platí pro body do radius_m; OSM/OCM ji neznají."""
    from . import geo
    if not (body.operator or body.name):
        raise HTTPException(status_code=400, detail="Zadej provozovatele nebo název")
    return await geo.add_user_place(body.lat, body.lon, body.operator, body.name, body.place, max(30, min(2000, body.radius_m)), user.get("username"))


@router.delete("/geo-places/{pid}")
async def geo_place_del(pid: int, _: dict = Depends(admin)):
    from . import geo
    await geo.delete_user_place(pid)
    return {"ok": True}


@router.post("/geo-retry")
async def geo_retry(_: dict = Depends(admin)):
    """Smaže z cache místa bez provozovatele → při příštím otevření detailu se dohledají znovu (zrcadla + OCM)."""
    from ems.api.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.fetchval("WITH d AS (DELETE FROM geo_cache WHERE operator IS NULL RETURNING 1) SELECT count(*) FROM d")
    return {"deleted": n}


@router.get("/roles")
async def roles(_: dict = Depends(read)):
    return {"roles": db.ROLES, "role_labels": db.ROLE_LABELS, "default_key_map": db.DEFAULT_KEY_MAP,
            "stream_keys": [{"key": k, "why": w} for k, w in db.STREAM_KEYS]}
