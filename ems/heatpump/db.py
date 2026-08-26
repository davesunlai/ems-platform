"""Datový model tepelného čerpadla: hp_telemetry (hypertable, 30 s snapshoty).

hp_runs + hp_daily přijdou v dalším kroku (v0.64.1) — edge detektor a agregace.
Denní energie se budou počítat z *_today (max za den), protože *_total čítače
na ověřeném kuse vracejí 0 (nespolehlivý 35xx FW) — viz docs/STIEBEL-ISG-BRIEF.md.
"""
from __future__ import annotations

from ems.api.db import get_pool

_COLS = ("t_outdoor", "t_tank", "t_buffer", "t_buffer_set", "p_heating",
         "compressor_on", "hp_mode", "nhz_on", "defrost", "evu_blocked",
         "fault", "error_code", "operating_mode", "sg_state",
         "el_heating_today_kwh", "el_dhw_today_kwh",
         "heat_heating_today_kwh", "heat_dhw_today_kwh",
         "el_heating_total_kwh", "el_dhw_total_kwh",
         "heat_heating_total_kwh", "heat_dhw_total_kwh", "power_est_w")


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hp_telemetry (
                ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                module_id TEXT NOT NULL,
                t_outdoor DOUBLE PRECISION, t_tank DOUBLE PRECISION,
                t_buffer DOUBLE PRECISION, t_buffer_set DOUBLE PRECISION,
                p_heating DOUBLE PRECISION,
                compressor_on BOOLEAN, hp_mode TEXT, nhz_on BOOLEAN,
                defrost BOOLEAN, evu_blocked BOOLEAN, fault BOOLEAN,
                error_code INTEGER, operating_mode INTEGER, sg_state INTEGER,
                el_heating_today_kwh DOUBLE PRECISION, el_dhw_today_kwh DOUBLE PRECISION,
                heat_heating_today_kwh DOUBLE PRECISION, heat_dhw_today_kwh DOUBLE PRECISION,
                el_heating_total_kwh DOUBLE PRECISION, el_dhw_total_kwh DOUBLE PRECISION,
                heat_heating_total_kwh DOUBLE PRECISION, heat_dhw_total_kwh DOUBLE PRECISION,
                power_est_w DOUBLE PRECISION
            )
            """
        )
        try:
            await conn.execute(
                "SELECT create_hypertable('hp_telemetry', 'ts', if_not_exists => TRUE)")
        except Exception:
            pass
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hp_tel_mod_ts ON hp_telemetry (module_id, ts DESC)")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hp_runs (
                id SERIAL PRIMARY KEY,
                module_id TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'heating',
                started_at TIMESTAMPTZ NOT NULL,
                ended_at TIMESTAMPTZ,
                t_outdoor_start DOUBLE PRECISION,
                el_kwh DOUBLE PRECISION,
                heat_kwh DOUBLE PRECISION,
                acc_el_kwh DOUBLE PRECISION NOT NULL DEFAULT 0,
                acc_heat_kwh DOUBLE PRECISION NOT NULL DEFAULT 0
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hp_runs_mod_start ON hp_runs (module_id, started_at DESC)")


async def insert(module_id: str, d: dict) -> None:
    pool = await get_pool()
    cols = ", ".join(_COLS)
    ph = ", ".join(f"${i + 2}" for i in range(len(_COLS)))
    vals = []
    for c in _COLS:
        k = {"t_tank": "t_hc1"}.get(c, c)
        vals.append(d.get(k))
    async with pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO hp_telemetry (module_id, {cols}) VALUES ($1, {ph})",
            module_id, *vals)


async def latest_for_modules(module_ids: list[str]) -> dict | None:
    if not module_ids:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM hp_telemetry WHERE module_id = ANY($1::text[]) "
            "ORDER BY ts DESC LIMIT 1", module_ids)
    return dict(row) if row else None


async def daily(module_ids: list[str], start, end) -> list[dict]:
    """Denní agregace (pražské dny) z hp_telemetry (*_today max/den — totals jsou na kusu mrtvé)
    + runtime a počty startů z hp_runs. COP jen když el > 0."""
    if not module_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT (ts AT TIME ZONE 'Europe/Prague')::date AS day,
                   max(el_heating_today_kwh) AS el_heating, max(el_dhw_today_kwh) AS el_dhw,
                   max(heat_heating_today_kwh) AS heat_heating, max(heat_dhw_today_kwh) AS heat_dhw
            FROM hp_telemetry
            WHERE module_id = ANY($1::text[]) AND ts >= $2 AND ts < $3
            GROUP BY 1 ORDER BY 1
            """, module_ids, start, end)
        runs = await conn.fetch(
            """
            SELECT (started_at AT TIME ZONE 'Europe/Prague')::date AS day,
                   count(*) AS n_starts,
                   sum(EXTRACT(EPOCH FROM (COALESCE(ended_at, now()) - started_at)) / 60.0) AS runtime_min
            FROM hp_runs
            WHERE module_id = ANY($1::text[]) AND started_at >= $2 AND started_at < $3
            GROUP BY 1
            """, module_ids, start, end)
    rmap = {r["day"]: r for r in runs}
    out = []
    for r in rows:
        el = (r["el_heating"] or 0) + (r["el_dhw"] or 0)
        heat = (r["heat_heating"] or 0) + (r["heat_dhw"] or 0)
        rr = rmap.get(r["day"])
        out.append({
            "day": r["day"].isoformat(),
            "el_heating_kwh": round(r["el_heating"] or 0, 1), "el_dhw_kwh": round(r["el_dhw"] or 0, 1),
            "heat_heating_kwh": round(r["heat_heating"] or 0, 1), "heat_dhw_kwh": round(r["heat_dhw"] or 0, 1),
            "el_kwh": round(el, 1), "heat_kwh": round(heat, 1),
            "cop": round(heat / el, 2) if el > 0 else None,
            "runtime_min": round(float(rr["runtime_min"]), 0) if rr else 0,
            "n_starts": int(rr["n_starts"]) if rr else 0,
        })
    return out


async def runs(module_ids: list[str], limit: int = 50) -> list[dict]:
    if not module_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, module_id, mode, started_at, ended_at, t_outdoor_start, "
            "COALESCE(el_kwh, acc_el_kwh) AS el_kwh, COALESCE(heat_kwh, acc_heat_kwh) AS heat_kwh "
            "FROM hp_runs WHERE module_id = ANY($1::text[]) ORDER BY started_at DESC LIMIT $2",
            module_ids, limit)
    out = []
    for r in rows:
        d = dict(r)
        d["started_at"] = d["started_at"].isoformat()
        d["ended_at"] = d["ended_at"].isoformat() if d["ended_at"] else None
        out.append(d)
    return out
