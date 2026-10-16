"""🔋 Hlídání nerovnováhy článků baterie — konfigurace per lokalita + denní kontrola."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ems.api.db import get_pool

DEFAULTS = {"enabled": False, "soc_low": 30.0, "delta_low_mv": 200.0, "soc_high": 80.0, "delta_high_mv": 150.0,
            "check_hour": 6}
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
            """INSERT INTO cell_alert_config (locality_id, enabled, soc_low, delta_low_mv, soc_high, delta_high_mv, check_hour)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (locality_id) DO UPDATE SET enabled=$2, soc_low=$3, delta_low_mv=$4, soc_high=$5,
                 delta_high_mv=$6, check_hour=$7""",
            locality_id, bool(vals["enabled"]), float(vals["soc_low"]), float(vals["delta_low_mv"]),
            float(vals["soc_high"]), float(vals["delta_high_mv"]), int(vals["check_hour"]))
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
