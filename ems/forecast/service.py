"""Orchestrace predikce: pro lokalitu stáhni počasí per blok, spočítej výrobu,
sečti, ulož do cache; pak dolaď PR. Čte jen konfiguraci, žádné řízení.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ems.localities import db as loc_db
from . import calibrate, db as fdb
from . import model as pv_model
from .providers import OpenMeteoProvider, ForecastSolarProvider

logger = logging.getLogger("ems.forecast")
FS_MIN_INTERVAL_S = 9000   # Forecast.Solar přefetch nejdřív po ~2.5 h (limit 12/hod)


def _group_blocks(blocks: list[dict], total_kwp: float) -> list[dict]:
    """Sloučí bloky stejné orientace (tilt, azimut, typ) do skupin se součtem kWp."""
    groups: dict = {}
    for b in blocks:
        key = (round(b["tilt"], 1), round(b["azimuth"], 1), b["panel_type"])
        kwp = total_kwp * (b["share_pct"] or 0) / 100.0
        g = groups.setdefault(key, {"tilt": b["tilt"], "azimuth": b["azimuth"],
                                    "panel_type": b["panel_type"], "kwp": 0.0, "pr_w": 0.0})
        g["kwp"] += kwp
        g["pr_w"] += b["pr"] * kwp     # vážený PR
    out = []
    for g in groups.values():
        g["pr"] = (g["pr_w"] / g["kwp"]) if g["kwp"] > 0 else 0.8
        out.append(g)
    return out


def _to_map(series: list[dict]) -> dict:
    """{ts(datetime) -> pv_w}, klíč normalizovaný na UTC celou hodinu."""
    m = {}
    for r in series:
        ts = r["ts"]
        key = ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        m[key] = r["pv_w"]
    return m


def _average_with_band(om: list[dict], fs_map: dict) -> list[dict]:
    """Na gridu Open-Meteo: avg + pásmo (min/max přes dostupné zdroje)."""
    out = []
    for r in om:
        ts = r["ts"]
        key = ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        vals = [r["pv_w"]]
        if key in fs_map:
            vals.append(fs_map[key])
        avg = sum(vals) / len(vals)
        out.append({"ts": ts, "pv_w": avg, "pv_w_lo": min(vals), "pv_w_hi": max(vals)})
    return out


async def refresh_locality(locality_id: int) -> dict:
    loc = await loc_db.get(locality_id)
    if not loc:
        return {"ok": False, "reason": "lokalita nenalezena"}
    lat, lon = loc.get("lat"), loc.get("lon")
    total_kwp = float(loc.get("pv_kwp_total") or 0)
    if lat is None or lon is None:
        return {"ok": False, "reason": "chybí lat/lon lokality"}
    all_blocks = await fdb.list_blocks(locality_id)
    blocks = [b for b in all_blocks if b["enabled"]]
    if total_kwp <= 0:
        return {"ok": False, "reason": "chybí celkové kWp lokality (pole 'FVE kWp celkem')"}
    if not blocks:
        reason = "PV bloky nejsou uložené" if not all_blocks else "PV bloky jsou všechny vypnuté"
        return {"ok": False, "reason": reason}

    groups = _group_blocks(blocks, total_kwp)
    fetched_at = datetime.now(timezone.utc)
    om = OpenMeteoProvider()
    fs = ForecastSolarProvider()

    # Forecast.Solar přefetchujeme jen občas (limit) — jinak recyklujeme cache.
    last_fs = await fdb.latest_fetched_at(locality_id, "forecast_solar")
    fs_due = last_fs is None or (fetched_at - last_fs).total_seconds() >= FS_MIN_INTERVAL_S

    om_series_list, fs_series_list, weather_repr = [], [], None
    for g in groups:
        try:
            weather = await om.fetch(lat, lon, g["tilt"], g["azimuth"])
            if weather_repr is None:
                weather_repr = weather
            om_series_list.append(pv_model.block_series(g["kwp"], g["pr"], g["panel_type"], weather))
        except Exception as exc:
            logger.warning("Open-Meteo skupina %s lok %s: %s", g["azimuth"], locality_id, exc)
        if fs_due:
            try:
                raw = await fs.fetch(lat, lon, g["tilt"], g["azimuth"], g["kwp"])
                if g["panel_type"] == "bifacial":
                    raw = [{"ts": r["ts"], "pv_w": r["pv_w"] * (1 + pv_model.BIFACIAL_GAIN)} for r in raw]
                fs_series_list.append(raw)
            except Exception as exc:
                logger.info("Forecast.Solar skupina %s lok %s: %s (fallback)", g["azimuth"], locality_id, exc)

    if not om_series_list:
        return {"ok": False, "reason": "žádná data z Open-Meteo"}
    om_total = pv_model.sum_series(om_series_list)

    # Forecast.Solar: čerstvé sečíst a uložit, jinak recyklovat z cache pro pásmo.
    fs_fresh = bool(fs_series_list)
    if fs_fresh:
        fs_total = pv_model.sum_series(fs_series_list)
        await fdb.write_pv(locality_id, "forecast_solar", fs_total, fetched_at, pv_model.MODEL_VERSION)
        fs_map = _to_map(fs_total)
    else:
        cached = await fdb.latest_pv(locality_id, "forecast_solar")
        fs_map = _to_map([{"ts": datetime.fromisoformat(r["ts"]), "pv_w": r["pv_w"]} for r in cached]) if cached else {}

    avg = _average_with_band(om_total, fs_map)
    await fdb.write_pv(locality_id, "open_meteo", om_total, fetched_at, pv_model.MODEL_VERSION)
    await fdb.write_pv(locality_id, "avg", avg, fetched_at, pv_model.MODEL_VERSION)
    if weather_repr:
        await fdb.write_weather(locality_id, "open_meteo", weather_repr, fetched_at)

    try:
        devs = [d["id"] for d in await loc_db.devices_for_locality(locality_id)]
        await calibrate.calibrate(locality_id, devs)
    except Exception as exc:
        logger.debug("Kalibrace PR lokalita %s: %s", locality_id, exc)

    logger.info("Forecast lok %s: %d bodů, zdroje=%s", locality_id, len(avg),
                "OM+FS" if fs_map else "OM")
    return {"ok": True, "points": len(avg), "sources": (2 if fs_map else 1),
            "fetched_at": fetched_at.isoformat()}


async def refresh_all() -> None:
    """Projede lokality, které mají lat/lon i PV bloky."""
    try:
        locs = await loc_db.list_all()
    except Exception as exc:
        logger.debug("forecast refresh_all: %s", exc)
        return
    for loc in locs:
        lid = loc["id"] if isinstance(loc, dict) else getattr(loc, "id", None)
        if lid is None:
            continue
        try:
            res = await refresh_locality(lid)
            if res.get("ok"):
                logger.info("Forecast lokalita %s: %s bodů", lid, res["points"])
        except Exception as exc:
            logger.warning("Forecast lokalita %s selhal: %s", lid, exc)
