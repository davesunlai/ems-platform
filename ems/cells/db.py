"""🔋 Hlídání nerovnováhy článků baterie — konfigurace per lokalita + denní kontrola."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ems.api.db import get_pool

DEFAULTS = {"enabled": False, "soc_low": 30.0, "delta_low_mv": 200.0, "soc_high": 80.0, "delta_high_mv": 150.0,
            "check_hour": 6, "y_min": 3.2, "y_max": 3.7}
_KEYS = tuple(DEFAULTS)


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS cell_alert_config (
                 locality_id INT PRIMARY KEY,
                 enabled BOOLEAN NOT NULL DEFAULT FALSE,
                 soc_low REAL NOT NULL DEFAULT 30,
                 delta_low_mv REAL NOT NULL DEFAULT 200,
                 soc_high REAL NOT NULL DEFAULT 80,
                 delta_high_mv REAL NOT NULL DEFAULT 150,
                 check_hour INT NOT NULL DEFAULT 6,
                 last_check_at TIMESTAMPTZ,
                 last_result JSONB)""")
        await conn.execute("ALTER TABLE cell_alert_config ADD COLUMN IF NOT EXISTS y_min REAL NOT NULL DEFAULT 3.2")
        await conn.execute("ALTER TABLE cell_alert_config ADD COLUMN IF NOT EXISTS y_max REAL NOT NULL DEFAULT 3.7")


def _row(r) -> dict:
    if not r:
        return {**DEFAULTS, "last_check_at": None, "last_result": None}
    d = dict(r)
    if isinstance(d.get("last_result"), str):
        try:
            d["last_result"] = json.loads(d["last_result"])
        except Exception:
            pass
    if d.get("last_check_at"):
        d["last_check_at"] = d["last_check_at"].isoformat()
    d.pop("locality_id", None)
    return d


async def get_config(locality_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM cell_alert_config WHERE locality_id = $1", locality_id)
    return _row(r)


async def put_config(locality_id: int, patch: dict) -> dict:
    cur = await get_config(locality_id)
    vals = {k: patch.get(k, cur.get(k, DEFAULTS[k])) for k in _KEYS}
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO cell_alert_config (locality_id, enabled, soc_low, delta_low_mv, soc_high, delta_high_mv, check_hour, y_min, y_max)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (locality_id) DO UPDATE SET enabled=$2, soc_low=$3, delta_low_mv=$4, soc_high=$5,
                 delta_high_mv=$6, check_hour=$7, y_min=$8, y_max=$9""",
            locality_id, bool(vals["enabled"]), float(vals["soc_low"]), float(vals["delta_low_mv"]),
            float(vals["soc_high"]), float(vals["delta_high_mv"]), int(vals["check_hour"]),
            float(vals["y_min"]), float(vals["y_max"]))
    return await get_config(locality_id)


async def enabled_localities() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM cell_alert_config WHERE enabled")
    return [{"locality_id": r["locality_id"], **_row(r)} for r in rows]


async def save_result(locality_id: int, result: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO cell_alert_config (locality_id, last_check_at, last_result) VALUES ($1, now(), $2::jsonb) "
            "ON CONFLICT (locality_id) DO UPDATE SET last_check_at = now(), last_result = $2::jsonb",
            locality_id, json.dumps(result, default=str))


async def cell_ranking(device_id: str, pack: int, minutes: int = 1440, offset: int = 0, top: int = 10) -> dict:
    """Žebříček článků za okno: kolikrát (minut) byl článek hlášen jako nejnižší / nejvyšší,
    k tomu jeho nejnižší (resp. nejvyšší) napětí a největší rozptyl packu v těch chvílích."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT time_bucket('1 minute', time) AS b, metric, avg(value) AS v
               FROM samples
               WHERE device_id = $1 AND metric = ANY($2::text[])
                 AND time > now() - make_interval(mins => $3 + $4) AND time <= now() - make_interval(mins => $4)
               GROUP BY b, metric""",
            device_id, [f"battery_cell_nmin_{pack}", f"battery_cell_nmax_{pack}",
                        f"battery_cell_vmin_{pack}", f"battery_cell_vmax_{pack}"], int(minutes), int(offset))
    by_t: dict = {}
    for r in rows:
        d = by_t.setdefault(r["b"], {})
        m = r["metric"]
        d["nmin" if "nmin" in m else "nmax" if "nmax" in m else "vmin" if "vmin" in m else "vmax"] = float(r["v"])
    mins: dict[int, dict] = {}
    maxs: dict[int, dict] = {}
    for d in by_t.values():
        if "vmin" not in d or "vmax" not in d:
            continue
        delta = (d["vmax"] - d["vmin"]) * 1000.0
        if "nmin" in d:
            c = int(round(d["nmin"]))
            e = mins.setdefault(c, {"cell": c, "count": 0, "v": d["vmin"], "delta_mv": 0.0})
            e["count"] += 1
            e["v"] = min(e["v"], d["vmin"])
            e["delta_mv"] = max(e["delta_mv"], delta)
        if "nmax" in d:
            c = int(round(d["nmax"]))
            e = maxs.setdefault(c, {"cell": c, "count": 0, "v": d["vmax"], "delta_mv": 0.0})
            e["count"] += 1
            e["v"] = max(e["v"], d["vmax"])
            e["delta_mv"] = max(e["delta_mv"], delta)
    fmt = lambda lst: [{**e, "v": round(e["v"], 3), "delta_mv": round(e["delta_mv"])}
                       for e in sorted(lst.values(), key=lambda x: (-x["count"], x["cell"]))[:top]]
    return {"pack": pack, "minutes_total": len(by_t), "worst": fmt(mins), "best": fmt(maxs)}


async def pack_series(device_id: str, pack: int, hours: int = 24) -> list[dict]:
    """Minutové řady SoC packu + Umin/Umax článku za posledních N hodin → [{t, soc, vmin, vmax}]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT time_bucket('1 minute', time) AS b, metric, avg(value) AS v
               FROM samples
               WHERE device_id = $1 AND metric = ANY($2::text[]) AND time > now() - ($3 || ' hours')::interval
               GROUP BY b, metric ORDER BY b""",
            device_id, [f"battery_soc_{pack}", f"battery_cell_vmin_{pack}", f"battery_cell_vmax_{pack}"], str(hours))
    by_t: dict[datetime, dict] = {}
    for r in rows:
        d = by_t.setdefault(r["b"], {"t": r["b"]})
        m = r["metric"]
        d["soc" if m.endswith(f"soc_{pack}") else "vmin" if "vmin" in m else "vmax"] = float(r["v"])
    return [d for d in by_t.values() if "soc" in d and "vmin" in d and "vmax" in d]
