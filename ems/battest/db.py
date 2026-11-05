"""Tabulky testu baterie: battery_tests (jeden běžící na modul = zámek řízení), battery_test_snapshots (po 10 % SoC),
battery_test_log (události). Energie se integruje z hypertable samples (metric battery_power, DC strana baterie)."""
from __future__ import annotations

import json
from datetime import datetime

from ems.api.db import get_pool

RUNNING = ("preparing", "discharge0", "charge", "hold", "discharge")


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS battery_tests (
                id SERIAL PRIMARY KEY,
                locality_id INTEGER,
                module_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'preparing',   -- preparing|discharge0|charge|hold|discharge|done|aborted
                params JSONB NOT NULL DEFAULT '{}'::jsonb,   -- p_chg_kw, p_dis_kw, hold_min, floor_pct, ceil_pct, capacity_kwh
                saved JSONB NOT NULL DEFAULT '{}'::jsonb,    -- původní nastavení měniče (43024), stav wallboxu, pomocné čítače
                result JSONB,
                created_by TEXT,
                started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                phase_started_at TIMESTAMPTZ,
                ended_at TIMESTAMPTZ,
                abort_reason TEXT,
                note TEXT
            )""")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_battery_tests_mod ON battery_tests (module_id, started_at DESC)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS battery_test_snapshots (
                id SERIAL PRIMARY KEY,
                test_id INTEGER NOT NULL REFERENCES battery_tests(id) ON DELETE CASCADE,
                phase TEXT NOT NULL,
                soc_step INTEGER NOT NULL,                  -- průchod 10/20/…/100 (%), u hold 100
                ts TIMESTAMPTZ NOT NULL,
                soc REAL, soc1 REAL, soc2 REAL,
                e_phase_kwh DOUBLE PRECISION,               -- ∫|P_bat| od začátku fáze (kWh, DC strana)
                e_step_kwh DOUBLE PRECISION,                -- od předchozího snímku
                minutes_step REAL,
                bat_w REAL, grid_w REAL, pv_w REAL, load_w REAL,
                u1 REAL, u2 REAL, i1 REAL, i2 REAL,
                cell_vmin REAL, cell_vmax REAL, t_min REAL, t_max REAL,
                inv_chg_total REAL, inv_dis_total REAL,     -- čítače měniče (kontrola)
                note TEXT
            )""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS battery_test_log (
                id SERIAL PRIMARY KEY,
                test_id INTEGER NOT NULL REFERENCES battery_tests(id) ON DELETE CASCADE,
                ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                level TEXT NOT NULL DEFAULT 'info',
                msg TEXT NOT NULL
            )""")
        await conn.execute("ALTER TABLE localities ADD COLUMN IF NOT EXISTS main_breaker_a REAL")
        for c in ("cell_vmin_1", "cell_vmax_1", "cell_vmin_2", "cell_vmax_2", "cell_nmin_1", "cell_nmax_1", "cell_nmin_2", "cell_nmax_2", "cpm_1", "cpm_2"):
            await conn.execute(f"ALTER TABLE battery_test_snapshots ADD COLUMN IF NOT EXISTS {c} REAL")


def _row(r) -> dict:
    d = dict(r)
    for k in ("params", "saved", "result"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    for k in ("started_at", "phase_started_at", "ended_at", "ts"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    return d


async def running(module_id: str | None = None) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if module_id:
            rows = await conn.fetch("SELECT * FROM battery_tests WHERE module_id=$1 AND status = ANY($2::text[]) ORDER BY id DESC", module_id, list(RUNNING))
        else:
            rows = await conn.fetch("SELECT * FROM battery_tests WHERE status = ANY($1::text[]) ORDER BY id DESC", list(RUNNING))
    return [_row(r) for r in rows]


async def running_modules() -> set[str]:
    return {t["module_id"] for t in await running()}


async def create(locality_id: int, module_id: str, params: dict, saved: dict, created_by: str | None) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "INSERT INTO battery_tests (locality_id, module_id, params, saved, created_by, phase_started_at) "
            "VALUES ($1,$2,$3::jsonb,$4::jsonb,$5, now()) RETURNING *",
            locality_id, module_id, json.dumps(params), json.dumps(saved), created_by)
    return _row(r)


async def update(test_id: int, **fields) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        if k in ("params", "saved", "result") and v is not None:
            vals.append(json.dumps(v)); cols.append(f"{k}=${len(vals)}::jsonb")
        else:
            vals.append(v); cols.append(f"{k}=${len(vals)}")
    vals.append(test_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE battery_tests SET {', '.join(cols)} WHERE id=${len(vals)}", *vals)


async def get(test_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM battery_tests WHERE id=$1", test_id)
        if not r:
            return None
        snaps = await conn.fetch("SELECT * FROM battery_test_snapshots WHERE test_id=$1 ORDER BY ts", test_id)
        log = await conn.fetch("SELECT ts, level, msg FROM battery_test_log WHERE test_id=$1 ORDER BY ts", test_id)
    d = _row(r)
    d["snapshots"] = [_row(s) for s in snaps]
    d["log"] = [{"ts": l["ts"].isoformat(), "level": l["level"], "msg": l["msg"]} for l in log]
    return d


async def list_tests(locality_id: int | None, limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if locality_id is None:
            rows = await conn.fetch("SELECT * FROM battery_tests ORDER BY id DESC LIMIT $1", limit)
        else:
            rows = await conn.fetch("SELECT * FROM battery_tests WHERE locality_id=$1 ORDER BY id DESC LIMIT $2", locality_id, limit)
    return [_row(r) for r in rows]


async def log(test_id: int, msg: str, level: str = "info") -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO battery_test_log (test_id, level, msg) VALUES ($1,$2,$3)", test_id, level, msg[:500])


async def add_snapshot(test_id: int, **f) -> None:
    cols = list(f)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO battery_test_snapshots (test_id, {', '.join(cols)}) VALUES ($1, {', '.join(f'${i+2}' for i in range(len(cols)))})",
            test_id, *[f[c] for c in cols])


async def last_snapshot(test_id: int, phase: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM battery_test_snapshots WHERE test_id=$1 AND phase=$2 ORDER BY ts DESC LIMIT 1", test_id, phase)
    return _row(r) if r else None


async def energy_kwh(device_id: str, t0: datetime, t1: datetime, metric: str = "battery_power") -> tuple[float, float]:
    """(nabito, vybito) kWh z metriky výkonu (+ nabíjení / − vybíjení) lichoběžníkem; Δt omezeno na 60 s (výpadky).
    metric: battery_power (celek), battery_power_1 / battery_power_2 (packy)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("""
            WITH s AS (
              SELECT time, value, lead(time) OVER (ORDER BY time) AS t2, lead(value) OVER (ORDER BY time) AS v2
              FROM samples WHERE device_id=$1 AND metric=$4 AND time >= $2::timestamptz AND time <= $3::timestamptz)
            SELECT COALESCE(SUM(CASE WHEN (value+v2)/2 > 0 THEN (value+v2)/2 * LEAST(EXTRACT(EPOCH FROM (t2-time)), 60) END),0)/3.6e6 AS chg,
                   COALESCE(SUM(CASE WHEN (value+v2)/2 < 0 THEN -(value+v2)/2 * LEAST(EXTRACT(EPOCH FROM (t2-time)), 60) END),0)/3.6e6 AS dis
            FROM s WHERE t2 IS NOT NULL""", device_id, t0, t1, metric)
    return float(r["chg"] or 0), float(r["dis"] or 0)


async def metrics_at(device_id: str, metrics: list[str], ts: datetime, max_age_s: int = 300) -> dict:
    """Poslední hodnota každé metriky k okamžiku ts (pro dopočet u starších snímků)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT ON (metric) metric, value FROM samples WHERE device_id=$1 AND metric = ANY($2::text[]) "
            "AND time <= $3::timestamptz AND time > $3::timestamptz - make_interval(secs => $4) ORDER BY metric, time DESC", device_id, metrics, ts, max_age_s)
    return {r["metric"]: float(r["value"]) for r in rows}


async def latest_metrics(device_id: str, metrics: list[str], max_age_s: int = 180) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT ON (metric) metric, value, time FROM samples WHERE device_id=$1 AND metric = ANY($2::text[]) "
            "AND time > now() - make_interval(secs => $3) ORDER BY metric, time DESC", device_id, metrics, max_age_s)
    return {r["metric"]: float(r["value"]) for r in rows}


async def series(device_id: str, t0: datetime, t1: datetime) -> list[dict]:
    """Průběh po minutě: výkon baterie (W, + nabíjení / − vybíjení), SoC, síť, FVE."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT time_bucket('1 minute', time) AS t,
                   avg(value) FILTER (WHERE metric='battery_power') AS bat_w,
                   avg(value) FILTER (WHERE metric='battery_soc') AS soc,
                   avg(value) FILTER (WHERE metric='battery_soc_1') AS soc1,
                   avg(value) FILTER (WHERE metric='battery_soc_2') AS soc2,
                   avg(value) FILTER (WHERE metric='battery_power_1') AS bat1_w,
                   avg(value) FILTER (WHERE metric='battery_power_2') AS bat2_w,
                   avg(value) FILTER (WHERE metric='grid_power') AS grid_w,
                   avg(value) FILTER (WHERE metric='pv_power') AS pv_w
            FROM samples WHERE device_id=$1 AND metric IN ('battery_power','battery_soc','battery_soc_1','battery_soc_2','battery_power_1','battery_power_2','grid_power','pv_power')
              AND time >= $2::timestamptz AND time <= $3::timestamptz
            GROUP BY t ORDER BY t""", device_id, t0, t1)
    return [{"ts": r["t"].isoformat(), "bat_w": r["bat_w"], "soc": r["soc"], "soc1": r["soc1"], "soc2": r["soc2"],
             "bat1_w": r["bat1_w"], "bat2_w": r["bat2_w"], "grid_w": r["grid_w"], "pv_w": r["pv_w"]} for r in rows]


async def phase_marks(test_id: int) -> list[dict]:
    """Začátky fází z protokolu (log) — pro stínování grafu."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT ts, msg FROM battery_test_log WHERE test_id=$1 ORDER BY ts", test_id)
    out = []
    for r in rows:
        m = r["msg"]
        ph = ("discharge0" if ("fáze 0" in m or "Krok 1" in m) else "charge" if ("→ nabíjení" in m or "→ Krok 2" in m)
              else "hold" if ("→ výdrž" in m or "→ Krok 3" in m) else "discharge" if ("→ vybíjení" in m or "→ Krok 4" in m) else None)
        if ph:
            out.append({"phase": ph, "ts": r["ts"].isoformat()})
    return out
