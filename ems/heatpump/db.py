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
