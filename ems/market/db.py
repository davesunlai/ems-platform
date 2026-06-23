"""Stav trhu (aktuální spotová cena) v DB — jednořádkový cache."""
from __future__ import annotations

from ems.api.db import get_pool


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_state (
                id         INT PRIMARY KEY DEFAULT 1,
                price      DOUBLE PRECISION,
                currency   TEXT NOT NULL DEFAULT 'CZK/MWh',
                manual     BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute("ALTER TABLE market_state ADD COLUMN IF NOT EXISTS curve JSONB")
        await conn.execute("INSERT INTO market_state (id) VALUES (1) ON CONFLICT DO NOTHING")


async def get_state() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT price, currency, manual, updated_at, curve FROM market_state WHERE id = 1")
    if not row:
        return {"price": None, "currency": "CZK/MWh", "manual": False, "updated_at": None, "curve": None}
    d = dict(row)
    d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
    if isinstance(d.get("curve"), str):
        import json
        d["curve"] = json.loads(d["curve"])
    return d


async def set_live_price(price: float) -> None:
    """Zapíše cenu z živého feedu (jen pokud není aktivní ruční override)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE market_state SET price = $1, updated_at = now() WHERE id = 1 AND manual = FALSE",
            price,
        )


async def set_manual(price: float) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE market_state SET price = $1, manual = TRUE, updated_at = now() WHERE id = 1",
            price,
        )


async def clear_manual() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE market_state SET manual = FALSE, updated_at = now() WHERE id = 1")


async def set_curve(curve: dict) -> None:
    import json
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE market_state SET curve = $1::jsonb WHERE id = 1", json.dumps(curve)
        )


async def ensure_history_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spot_history (
                slot  TIMESTAMPTZ PRIMARY KEY,
                price DOUBLE PRECISION NOT NULL
            )
            """
        )


async def upsert_slots(slots: list[dict]) -> None:
    """slots: [{start: ISO, price}] — uloží/aktualizuje 15min sloty."""
    from datetime import datetime
    if not slots:
        return
    rows = []
    for s in slots:
        try:
            rows.append((datetime.fromisoformat(s["start"]), float(s["price"])))
        except Exception:
            pass
    if not rows:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO spot_history (slot, price) VALUES ($1, $2) "
            "ON CONFLICT (slot) DO UPDATE SET price = EXCLUDED.price",
            rows,
        )


async def history_window(days: int = 1, target_points: int = 400) -> list[dict]:
    """Sloty od (dnešek - (days-1)) do konce zítřka, agregované na ~target bodů.

    days=1 => dnešek+zítřek v 15min; delší okna se zhrubnou (time_bucket).
    """
    bucket_seconds = max(900, int(days * 86400 / target_points))  # min 15 min
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time_bucket(($1 || ' seconds')::interval, slot) AS b, avg(price) AS price
            FROM spot_history
            WHERE slot >= date_trunc('day', now()) - ($2 || ' days')::interval
              AND slot <  date_trunc('day', now()) + interval '2 days'
            GROUP BY b
            ORDER BY b
            """,
            str(bucket_seconds), str(max(0, days - 1)),
        )
    return [{"start": r["b"].isoformat(), "price": float(r["price"])}
            for r in rows if r["price"] is not None]


async def future_slots(hours: float = 24) -> list[dict]:
    """Budoucí 15min spotové sloty od teď do +hours. [{slot: datetime, price: CZK/MWh}]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT slot, price FROM spot_history "
            "WHERE slot >= now() - interval '15 minutes' "
            f"AND slot <= now() + interval '{int(hours)} hours' ORDER BY slot")
    return [{"slot": r["slot"], "price": float(r["price"])} for r in rows if r["price"] is not None]
