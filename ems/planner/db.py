"""Konfigurace plánovače (per lokalita) + uložený plán (dispatch_schedule)."""
from __future__ import annotations

from datetime import datetime

from ems.api.db import get_pool

CONFIG_DEFAULTS = {
    "enabled": False,                 # řídí (zapisuje do měniče)? default NE
    "allow_grid_discharge": False,    # smí vybíjet do sítě? (43136 neověřen) default NE
    "capacity_kwh": 52.8,             # Solis 2× 26.4
    "soc_min_pct": 15.0,
    "outage_reserve_pct": 10.0,       # rezerva navíc pro výpadek
    "max_charge_kw": 10.0,
    "max_discharge_kw": 10.0,
    "horizon_h": 36,
}
_CFG_KEYS = list(CONFIG_DEFAULTS.keys())


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS planner_config (
                locality_id        INTEGER PRIMARY KEY,
                enabled            BOOLEAN NOT NULL DEFAULT FALSE,
                allow_grid_discharge BOOLEAN NOT NULL DEFAULT FALSE,
                capacity_kwh       DOUBLE PRECISION DEFAULT 52.8,
                soc_min_pct        DOUBLE PRECISION DEFAULT 15,
                outage_reserve_pct DOUBLE PRECISION DEFAULT 10,
                max_charge_kw      DOUBLE PRECISION DEFAULT 10,
                max_discharge_kw   DOUBLE PRECISION DEFAULT 10,
                horizon_h          INTEGER DEFAULT 36,
                updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dispatch_schedule (
                locality_id  INTEGER NOT NULL,
                ts           TIMESTAMPTZ NOT NULL,
                action       TEXT NOT NULL,
                battery_kw   DOUBLE PRECISION,
                soc_pct      DOUBLE PRECISION,
                import_kwh   DOUBLE PRECISION,
                export_kwh   DOUBLE PRECISION,
                price_import DOUBLE PRECISION,
                price_export DOUBLE PRECISION,
                reason       TEXT,
                fetched_at   TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (locality_id, ts)
            )
            """
        )


async def get_config(locality_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM planner_config WHERE locality_id=$1", locality_id)
    cfg = dict(CONFIG_DEFAULTS)
    cfg["locality_id"] = locality_id
    if row:
        for k in _CFG_KEYS:
            cfg[k] = row[k]
    return cfg


async def all_enabled() -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT locality_id FROM planner_config WHERE enabled=TRUE")
    return [r["locality_id"] for r in rows]


async def upsert_config(locality_id: int, patch: dict) -> dict:
    cur = await get_config(locality_id)
    cur.update({k: patch[k] for k in _CFG_KEYS if k in patch and patch[k] is not None})
    cols = ", ".join(["locality_id", *_CFG_KEYS])
    ph = ", ".join(f"${i}" for i in range(1, len(_CFG_KEYS) + 2))
    sets = ", ".join(f"{k}=EXCLUDED.{k}" for k in _CFG_KEYS)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"INSERT INTO planner_config ({cols}) VALUES ({ph}) "
            f"ON CONFLICT (locality_id) DO UPDATE SET {sets}, updated_at=now()",
            locality_id, *[cur[k] for k in _CFG_KEYS])
    return await get_config(locality_id)


async def write_schedule(locality_id: int, rows: list[dict], fetched_at: datetime) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM dispatch_schedule WHERE locality_id=$1", locality_id)
            if rows:
                await conn.executemany(
                    "INSERT INTO dispatch_schedule (locality_id, ts, action, battery_kw, soc_pct, "
                    "import_kwh, export_kwh, price_import, price_export, reason, fetched_at) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                    [(locality_id, r["ts"], r["action"], r["battery_kw"], r["soc_pct"],
                      r["import_kwh"], r["export_kwh"], r["price_import"], r["price_export"],
                      r["reason"], fetched_at) for r in rows])


async def latest_schedule(locality_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ts, action, battery_kw, soc_pct, import_kwh, export_kwh, "
            "price_import, price_export, reason FROM dispatch_schedule "
            "WHERE locality_id=$1 ORDER BY ts", locality_id)
    return [{**dict(r), "ts": r["ts"].isoformat()} for r in rows]


async def current_action(locality_id: int) -> dict | None:
    """Řádek plánu pro aktuální hodinu (pro výkon povelu kolektorem)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ts, action, battery_kw, soc_pct, reason FROM dispatch_schedule "
            "WHERE locality_id=$1 AND ts <= now() ORDER BY ts DESC LIMIT 1", locality_id)
    return dict(row) if row else None
