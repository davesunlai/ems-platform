"""Orchestrace predikce: pro lokalitu stáhni počasí per blok, spočítej výrobu,
sečti, ulož do cache; pak dolaď PR. Čte jen konfiguraci, žádné řízení.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ems.localities import db as loc_db
from . import calibrate, db as fdb
from . import model as pv_model
from .providers import OpenMeteoProvider

logger = logging.getLogger("ems.forecast")


async def refresh_locality(locality_id: int) -> dict:
    loc = await loc_db.get(locality_id)
    if not loc:
        return {"ok": False, "reason": "lokalita nenalezena"}
    lat, lon = loc.get("lat"), loc.get("lon")
    total_kwp = float(loc.get("pv_kwp_total") or 0)
    if lat is None or lon is None:
        return {"ok": False, "reason": "chybí lat/lon lokality"}
    blocks = [b for b in await fdb.list_blocks(locality_id) if b["enabled"]]
    if not blocks or total_kwp <= 0:
        return {"ok": False, "reason": "chybí PV bloky / kWp"}

    provider = OpenMeteoProvider()
    fetched_at = datetime.now(timezone.utc)
    series_list, weather_repr = [], None
    for b in blocks:
        block_kwp = total_kwp * (b["share_pct"] or 0) / 100.0
        try:
            weather = await provider.fetch(lat, lon, b["tilt"], b["azimuth"])
        except Exception as exc:
            logger.warning("Open-Meteo blok %s lokalita %s: %s", b["id"], locality_id, exc)
            continue
        if weather_repr is None:
            weather_repr = weather
        series_list.append(pv_model.block_series(block_kwp, b["pr"], b["panel_type"], weather))

    if not series_list:
        return {"ok": False, "reason": "žádná data z Open-Meteo"}

    total = pv_model.sum_series(series_list)
    # jediný zdroj zatím -> 'open_meteo' i 'avg' (avg doplní druhý zdroj v dalším kroku)
    await fdb.write_pv(locality_id, "open_meteo", total, fetched_at, pv_model.MODEL_VERSION)
    await fdb.write_pv(locality_id, "avg", total, fetched_at, pv_model.MODEL_VERSION)
    if weather_repr:
        await fdb.write_weather(locality_id, "open_meteo", weather_repr, fetched_at)

    # kalibrace PR (pro příští cyklus) — proti reálné výrobě měniče
    try:
        devs = [d["id"] for d in await loc_db.devices_for_locality(locality_id)]
        await calibrate.calibrate(locality_id, devs)
    except Exception as exc:
        logger.debug("Kalibrace PR lokalita %s: %s", locality_id, exc)

    return {"ok": True, "points": len(total), "fetched_at": fetched_at.isoformat()}


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
