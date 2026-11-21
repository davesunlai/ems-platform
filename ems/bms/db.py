"""Napětí a teploty všech článků BMS (Pylontech SC0500 po RS485) — jeden řádek na blok a okamžik, hodnoty v polích.
Ukládá se 1× za STORE_S (5 min), při běžícím testu baterie 1× za STORE_TEST_S (1 min)."""
from __future__ import annotations

import time as _time
from datetime import datetime

from ems.api.db import get_pool

STORE_S, STORE_TEST_S = 300.0, 55.0
KEEP_DAYS = 400
_last: dict[str, float] = {}
_test_cache = {"t": 0.0, "running": False}


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bms_cells (
                device_id TEXT NOT NULL,
                time TIMESTAMPTZ NOT NULL,
                mv INTEGER[] NOT NULL,            -- napětí článků v mV, pořadí = číslo článku 1..N
                temp SMALLINT[],                  -- teplota u článku ×0,1 °C
                module_cv INTEGER[],              -- napětí modulů ×0,01 V
                module_temp SMALLINT[],           -- teplota modulů ×0,1 °C
                PRIMARY KEY (device_id, time))""")


async def _test_running() -> bool:
    now = _time.monotonic()
    if now - _test_cache["t"] > 30:
        _test_cache["t"] = now
        try:
            from ems.battest import db as bt_db
            _test_cache["running"] = bool(await bt_db.running())
        except Exception:
            _test_cache["running"] = False
    return _test_cache["running"]


async def maybe_store(device_id: str, ts: datetime, arrays: dict) -> bool:
    mv = arrays.get("bms_cells_mv")
    if not mv:
        return False
    t = ts.timestamp()
    every = STORE_TEST_S if await _test_running() else STORE_S
    last = _last.get(device_id)
    if last is not None and 0 <= t - last < every:
        return False
    _last[device_id] = t
    ints = lambda k: [int(round(x)) for x in arrays[k]] if arrays.get(k) else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bms_cells (device_id, time, mv, temp, module_cv, module_temp) VALUES ($1,$2,$3,$4,$5,$6) "
            "ON CONFLICT (device_id, time) DO NOTHING",
            device_id, ts, ints("bms_cells_mv"), ints("bms_cells_temp"), ints("bms_modules_cv"), ints("bms_modules_temp"))
    return True


async def latest(device_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM bms_cells WHERE device_id=$1 ORDER BY time DESC LIMIT 1", device_id)
    if not r:
        return None
    return {"time": r["time"].isoformat(), "mv": list(r["mv"]), "temp": list(r["temp"] or []),
            "module_cv": list(r["module_cv"] or []), "module_temp": list(r["module_temp"] or [])}


async def cleanup() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM bms_cells WHERE time < now() - ($1 || ' days')::interval", str(KEEP_DAYS))
