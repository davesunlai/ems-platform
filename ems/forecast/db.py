"""Cache predikce počasí/výroby + konfigurace PV bloků lokality.

Čtecí vrstva: služba zapisuje řady, dashboard čte jen poslední `fetched_at`.
"""
from __future__ import annotations

import json
from datetime import datetime

from ems.api.db import get_pool


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_forecast (
                locality_id INTEGER NOT NULL,
                ts          TIMESTAMPTZ NOT NULL,
                source      TEXT NOT NULL,
                ghi         DOUBLE PRECISION,
                gti         DOUBLE PRECISION,
                temp_c      DOUBLE PRECISION,
                cloud_pct   DOUBLE PRECISION,
                fetched_at  TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (locality_id, source, ts)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pv_forecast (
                locality_id   INTEGER NOT NULL,
                ts            TIMESTAMPTZ NOT NULL,
                source        TEXT NOT NULL,
                pv_w          DOUBLE PRECISION NOT NULL,
                fetched_at    TIMESTAMPTZ NOT NULL,
                model_version TEXT,
                PRIMARY KEY (locality_id, source, ts)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS load_forecast (
                locality_id INTEGER NOT NULL,
                ts          TIMESTAMPTZ NOT NULL,
                load_w      DOUBLE PRECISION NOT NULL,
                fetched_at  TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (locality_id, ts)
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pv_block (
                id          SERIAL PRIMARY KEY,
                locality_id INTEGER NOT NULL,
                name        TEXT NOT NULL DEFAULT '',
                share_pct   DOUBLE PRECISION NOT NULL DEFAULT 100,
                panel_type  TEXT NOT NULL DEFAULT 'normal',   -- normal | bifacial
                tilt        DOUBLE PRECISION NOT NULL DEFAULT 30,
                azimuth     DOUBLE PRECISION NOT NULL DEFAULT 0,  -- 0=J, -90=V, +90=Z, ±180=S
                pr          DOUBLE PRECISION NOT NULL DEFAULT 0.8,
                enabled     BOOLEAN NOT NULL DEFAULT TRUE
            )
            """
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS pv_block_loc ON pv_block(locality_id)")
        # pásmo nejistoty (rozptyl zdrojů) — vyplněné jen u source='avg'
        for col in ("pv_w_lo", "pv_w_hi"):
            await conn.execute(f"ALTER TABLE pv_forecast ADD COLUMN IF NOT EXISTS {col} DOUBLE PRECISION")


# --- konfigurace bloků -------------------------------------------------------
async def list_blocks(locality_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, share_pct, panel_type, tilt, azimuth, pr, enabled "
            "FROM pv_block WHERE locality_id=$1 ORDER BY id", locality_id)
    return [dict(r) for r in rows]


async def replace_blocks(locality_id: int, blocks: list[dict]) -> None:
    """Atomicky nahradí všechny bloky lokality (admin uloží celý seznam)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM pv_block WHERE locality_id=$1", locality_id)
            for b in blocks:
                await conn.execute(
                    "INSERT INTO pv_block (locality_id, name, share_pct, panel_type, tilt, azimuth, pr, enabled) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                    locality_id, b.get("name", ""), float(b.get("share_pct", 0) or 0),
                    b.get("panel_type", "normal"), float(b.get("tilt", 30) or 0),
                    float(b.get("azimuth", 0) or 0), float(b.get("pr", 0.8) or 0.8),
                    bool(b.get("enabled", True)))


async def set_block_pr(block_id: int, pr: float) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE pv_block SET pr=$2 WHERE id=$1", block_id, float(pr))


# --- cache zápis -------------------------------------------------------------
async def write_weather(locality_id: int, source: str, rows: list[dict], fetched_at: datetime) -> None:
    if not rows:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO weather_forecast (locality_id, ts, source, ghi, gti, temp_c, cloud_pct, fetched_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
            "ON CONFLICT (locality_id, source, ts) DO UPDATE SET "
            "ghi=EXCLUDED.ghi, gti=EXCLUDED.gti, temp_c=EXCLUDED.temp_c, "
            "cloud_pct=EXCLUDED.cloud_pct, fetched_at=EXCLUDED.fetched_at",
            [(locality_id, r["ts"], source, r.get("ghi"), r.get("gti"),
              r.get("temp_c"), r.get("cloud_pct"), fetched_at) for r in rows])


async def write_pv(locality_id: int, source: str, rows: list[dict], fetched_at: datetime,
                   model_version: str) -> None:
    if not rows:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO pv_forecast (locality_id, ts, source, pv_w, fetched_at, model_version, pv_w_lo, pv_w_hi) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
            "ON CONFLICT (locality_id, source, ts) DO UPDATE SET "
            "pv_w=EXCLUDED.pv_w, fetched_at=EXCLUDED.fetched_at, model_version=EXCLUDED.model_version, "
            "pv_w_lo=EXCLUDED.pv_w_lo, pv_w_hi=EXCLUDED.pv_w_hi",
            [(locality_id, r["ts"], source, float(r["pv_w"]), fetched_at, model_version,
              r.get("pv_w_lo"), r.get("pv_w_hi")) for r in rows])


# --- cache čtení (poslední řada) --------------------------------------------
async def latest_pv(locality_id: int, source: str = "avg") -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ts, pv_w, pv_w_lo, pv_w_hi FROM pv_forecast WHERE locality_id=$1 AND source=$2 "
            "AND fetched_at=(SELECT max(fetched_at) FROM pv_forecast WHERE locality_id=$1 AND source=$2) "
            "ORDER BY ts", locality_id, source)
    return [{"ts": r["ts"].isoformat(), "pv_w": r["pv_w"],
             "pv_w_lo": r["pv_w_lo"], "pv_w_hi": r["pv_w_hi"]} for r in rows]


async def latest_fetched_at(locality_id: int, source: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT max(fetched_at) FROM pv_forecast WHERE locality_id=$1 AND source=$2",
            locality_id, source)


# --- predikce zátěže ---------------------------------------------------------
async def write_load(locality_id: int, rows: list[dict], fetched_at: datetime) -> None:
    if not rows:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM load_forecast WHERE locality_id=$1", locality_id)
        await conn.executemany(
            "INSERT INTO load_forecast (locality_id, ts, load_w, fetched_at) VALUES ($1,$2,$3,$4)",
            [(locality_id, r["ts"], float(r["load_w"]), fetched_at) for r in rows])


async def latest_load(locality_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ts, load_w FROM load_forecast WHERE locality_id=$1 ORDER BY ts", locality_id)
    return [{"ts": r["ts"].isoformat(), "load_w": r["load_w"]} for r in rows]


# --- spot pro okno predikce (hodinově, CZK/MWh) ------------------------------
async def spot_window_hourly(hours: int = 48) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT time_bucket('1 hour', slot) AS h, avg(price) AS czk_mwh "
            "FROM spot_history "
            "WHERE slot >= date_trunc('hour', now()) AND slot < now() + ($1 || ' hours')::interval "
            "GROUP BY h ORDER BY h", str(hours))
    return [{"ts": r["h"].isoformat(), "czk_mwh": float(r["czk_mwh"])} for r in rows if r["czk_mwh"] is not None]


async def latest_pv_all_sources(locality_id: int) -> dict[str, list[dict]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        srcs = await conn.fetch("SELECT DISTINCT source FROM pv_forecast WHERE locality_id=$1", locality_id)
    out = {}
    for s in srcs:
        out[s["source"]] = await latest_pv(locality_id, s["source"])
    return out
