"""Versionovaný cenový model lokality (`locality_tariff`, valid_from) + cache
kurzu ČNB. Účtování i plánovač jsou jen čtenáři přes get_effective/price.

Spot bereme v CZK/MWh (zdroj spotovaelektrina.cz), takže kurz do ceny spotu
nevstupuje; ukládá se informativně / pro budoucí EUR složky.
"""
from __future__ import annotations

from datetime import date, datetime

from ems.api.db import get_pool

_FIELDS = (
    "mode", "monthly_fee", "two_tariff", "nt_hours",
    "spot_buy_surcharge", "spot_sell_fee", "dist_buy_vt", "dist_buy_nt", "levies",
    "fix_buy_vt", "fix_buy_nt", "fix_sell", "fx_source", "fx_eur_czk",
)

DEFAULTS = {
    "mode": "spot", "monthly_fee": 0.0, "two_tariff": False, "nt_hours": "",
    "spot_buy_surcharge": 0.0, "spot_sell_fee": 200.0, "dist_buy_vt": 0.0,
    "dist_buy_nt": 0.0, "levies": 0.0, "fix_buy_vt": 0.0, "fix_buy_nt": 0.0,
    "fix_sell": 0.0, "fx_source": "cnb", "fx_eur_czk": None,
}


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS locality_tariff (
                id          SERIAL PRIMARY KEY,
                locality_id INTEGER NOT NULL,
                valid_from  DATE NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                mode        TEXT NOT NULL DEFAULT 'spot',     -- 'spot' | 'fixed'
                monthly_fee DOUBLE PRECISION DEFAULT 0,
                two_tariff  BOOLEAN DEFAULT FALSE,
                nt_hours    TEXT DEFAULT '',                  -- CSV hodin NT 0-23 (pražský čas)
                -- SPOT složky (CZK/MWh):
                spot_buy_surcharge DOUBLE PRECISION DEFAULT 0,
                spot_sell_fee      DOUBLE PRECISION DEFAULT 0,  -- provize z prodeje (odečítá se)
                dist_buy_vt DOUBLE PRECISION DEFAULT 0,
                dist_buy_nt DOUBLE PRECISION DEFAULT 0,
                levies      DOUBLE PRECISION DEFAULT 0,
                -- FIXED složky (CZK/kWh):
                fix_buy_vt  DOUBLE PRECISION DEFAULT 0,
                fix_buy_nt  DOUBLE PRECISION DEFAULT 0,
                fix_sell    DOUBLE PRECISION DEFAULT 0,
                -- kurz:
                fx_source   TEXT DEFAULT 'cnb',               -- 'cnb' | 'fixed'
                fx_eur_czk  DOUBLE PRECISION
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS locality_tariff_loc ON locality_tariff(locality_id, valid_from DESC)")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fx_rate (
                day        DATE PRIMARY KEY,
                eur_czk    DOUBLE PRECISION NOT NULL,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


async def list_versions(locality_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, valid_from, " + ", ".join(_FIELDS) +
            " FROM locality_tariff WHERE locality_id=$1 ORDER BY valid_from DESC, id DESC", locality_id)
    return [dict(r) for r in rows]


async def get_effective(locality_id: int, at: date | None = None) -> dict | None:
    """Tarif platný k datu (max valid_from <= at)."""
    at = at or date.today()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, valid_from, " + ", ".join(_FIELDS) +
            " FROM locality_tariff WHERE locality_id=$1 AND valid_from<=$2 "
            "ORDER BY valid_from DESC, id DESC LIMIT 1", locality_id, at)
    return dict(row) if row else None


async def add_version(locality_id: int, valid_from: date, fields: dict) -> dict:
    vals = {k: fields.get(k, DEFAULTS[k]) for k in _FIELDS}
    cols = ", ".join(["locality_id", "valid_from", *_FIELDS])
    ph = ", ".join(f"${i}" for i in range(1, len(_FIELDS) + 3))
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"INSERT INTO locality_tariff ({cols}) VALUES ({ph}) RETURNING id, valid_from, " + ", ".join(_FIELDS),
            locality_id, valid_from, *[vals[k] for k in _FIELDS])
    return dict(row)


async def delete_version(version_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM locality_tariff WHERE id=$1", version_id)


# --- kurz ČNB ----------------------------------------------------------------
async def save_fx(day: date, eur_czk: float) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO fx_rate (day, eur_czk) VALUES ($1,$2) "
            "ON CONFLICT (day) DO UPDATE SET eur_czk=EXCLUDED.eur_czk, fetched_at=now()", day, eur_czk)


async def latest_fx() -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT day, eur_czk, fetched_at FROM fx_rate ORDER BY day DESC LIMIT 1")
    return dict(row) if row else None
