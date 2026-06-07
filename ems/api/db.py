"""Databázové dotazy pro API (TimescaleDB / PostgreSQL přes asyncpg)."""
from __future__ import annotations

import os
from datetime import timedelta


def _zero_fill_power(rows_dt: list[tuple], bucket_seconds: int, gap_factor: int = 3) -> list[tuple]:
    """Při výpadku dat (mezera > gap_factor košů) vloží nuly, aby čára spadla
    na 0 místo interpolace posledního a nového bodu. Pro výkonové veličiny."""
    if len(rows_dt) < 2:
        return rows_dt
    gap = bucket_seconds * gap_factor
    bucket = timedelta(seconds=bucket_seconds)
    out, prev_t = [], None
    for t, v in rows_dt:
        if prev_t is not None and (t - prev_t).total_seconds() > gap:
            out.append((prev_t + bucket, 0.0))
            out.append((t - bucket, 0.0))
        out.append((t, v))
        prev_t = t
    return out

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        import asyncpg
        dsn = os.getenv("EMS_DB_DSN", "postgresql://ems:ems@timescaledb:5432/ems")
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=8)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def list_devices() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.device_id,
                   max(l.name)  AS locality,
                   max(m.locality_id) AS locality_id,
                   max(s.time)  AS last_seen,
                   (max(s.time) > now() - interval '5 minutes') AS active
            FROM samples s
            LEFT JOIN modules m    ON m.id = s.device_id
            LEFT JOIN localities l ON l.id = m.locality_id
            GROUP BY s.device_id
            ORDER BY s.device_id
            """
        )
    return [{
        "device_id": r["device_id"],
        "locality": r["locality"],
        "locality_id": r["locality_id"],
        "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
        "active": bool(r["active"]),
    } for r in rows]


async def latest_for_device(device_id: str) -> list[dict]:
    """Poslední hodnota každé veličiny daného zařízení."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (metric) metric, value, unit, quality, time
            FROM samples
            WHERE device_id = $1
              AND time > now() - interval '5 minutes'
            ORDER BY metric, time DESC
            """,
            device_id,
        )
    return [dict(r) for r in rows]


async def history(device_id: str, metric: str, minutes: int = 360, offset: int = 0,
                  target_points: int = 400) -> list[dict]:
    # Okno [now-(minutes+offset), now-offset]; agregace do ~target_points košů.
    bucket_seconds = max(10, int(minutes * 60 / target_points))
    start_min = minutes + offset
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT time_bucket(($4 || ' seconds')::interval, time) AS bucket,
                   avg(value) AS value
            FROM samples
            WHERE device_id = $1 AND metric = $2
              AND time >  now() - ($3 || ' minutes')::interval
              AND time <= now() - ($5 || ' minutes')::interval
            GROUP BY bucket
            ORDER BY bucket
            """,
            device_id, metric, str(start_min), str(bucket_seconds), str(offset),
        )
    raw = [(r["bucket"], float(r["value"])) for r in rows if r["value"] is not None]
    if metric.endswith("_power"):
        raw = _zero_fill_power(raw, bucket_seconds)
    return [{"time": t.isoformat(), "value": v} for t, v in raw]


async def ensure_state_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS device_state (
                device_id  TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (device_id, key)
            )
            """
        )


async def latest_states(device_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value FROM device_state "
            "WHERE device_id = $1 AND updated_at > now() - interval '5 minutes'",
            device_id,
        )
    return {r["key"]: r["value"] for r in rows}


async def aggregate_now(device_ids: list[str]) -> dict:
    """Aktuální souhrn lokality: součet výkonu FVE (W), průměrný SoC (%), dnešní výroba (kWh)."""
    if not device_ids:
        return {"pv_w": 0.0, "soc": None, "today_kwh": 0.0}
    pool = await get_pool()
    async with pool.acquire() as conn:
        pv = await conn.fetchval(
            "SELECT COALESCE(SUM(v),0) FROM ("
            "  SELECT DISTINCT ON (device_id) value AS v FROM samples"
            "  WHERE device_id = ANY($1::text[]) AND metric='pv_power' AND time > now() - interval '5 minutes'"
            "  ORDER BY device_id, time DESC) t", device_ids)
        soc = await conn.fetchval(
            "SELECT AVG(v) FROM ("
            "  SELECT DISTINCT ON (device_id) value AS v FROM samples"
            "  WHERE device_id = ANY($1::text[]) AND metric='battery_soc' AND time > now() - interval '5 minutes'"
            "  ORDER BY device_id, time DESC) t", device_ids)
        kwh = await conn.fetchval(
            "SELECT COALESCE(SUM(mx - mn),0) FROM ("
            "  SELECT device_id, MAX(value) mx, MIN(value) mn FROM samples"
            "  WHERE device_id = ANY($1::text[]) AND metric='energy_pv_total'"
            "    AND time >= date_trunc('day', now() AT TIME ZONE 'Europe/Prague') AT TIME ZONE 'Europe/Prague'"
            "  GROUP BY device_id) t", device_ids)
    return {"pv_w": float(pv or 0), "soc": float(soc) if soc is not None else None, "today_kwh": float(kwh or 0)}


async def aggregate_history(device_ids: list[str], metric: str, minutes: int = 360,
                            offset: int = 0, target_points: int = 400) -> list[dict]:
    """Součet veličiny přes více zařízení v čase (per-bucket suma průměrů zařízení)."""
    if not device_ids:
        return []
    bucket_seconds = max(10, int(minutes * 60 / target_points))
    start_min = minutes + offset
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT b, sum(dev_avg) AS value FROM (
                SELECT time_bucket(($1 || ' seconds')::interval, time) AS b,
                       device_id, avg(value) AS dev_avg
                FROM samples
                WHERE device_id = ANY($2::text[]) AND metric = $3
                  AND time >  now() - ($4 || ' minutes')::interval
                  AND time <= now() - ($5 || ' minutes')::interval
                GROUP BY b, device_id
            ) t
            GROUP BY b ORDER BY b
            """,
            str(bucket_seconds), device_ids, metric, str(start_min), str(offset),
        )
    raw = [(r["b"], float(r["value"])) for r in rows if r["value"] is not None]
    if metric.endswith("_power"):
        raw = _zero_fill_power(raw, bucket_seconds)
    return [{"time": t.isoformat(), "value": v} for t, v in raw]
