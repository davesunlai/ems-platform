"""Úložiště plánovaných odstávek + identifikace lokality pro dotaz na distributora."""
from __future__ import annotations

import json

from ems.api.db import get_pool


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS planned_outages (
                uid         TEXT PRIMARY KEY,
                locality_id INTEGER REFERENCES localities(id) ON DELETE CASCADE,
                distributor TEXT NOT NULL,
                number      TEXT,
                start_at    TIMESTAMPTZ NOT NULL,
                end_at      TIMESTAMPTZ NOT NULL,
                locations   TEXT,
                raw         JSONB,
                fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outages_loc ON planned_outages (locality_id, start_at)"
        )


async def upsert_many(locality_id: int, outages: list) -> int:
    if not outages:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        for o in outages:
            await conn.execute(
                """
                INSERT INTO planned_outages
                    (uid, locality_id, distributor, number, start_at, end_at, locations, raw, fetched_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8, now())
                ON CONFLICT (uid) DO UPDATE SET
                    locality_id=EXCLUDED.locality_id, distributor=EXCLUDED.distributor,
                    number=EXCLUDED.number, start_at=EXCLUDED.start_at, end_at=EXCLUDED.end_at,
                    locations=EXCLUDED.locations, raw=EXCLUDED.raw, fetched_at=now()
                """,
                o.uid, locality_id, o.distributor, o.number, o.start, o.end,
                " | ".join(o.locations), json.dumps(o.raw, ensure_ascii=False),
            )
    return len(outages)


async def existing_uids(locality_id: int) -> set[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT uid FROM planned_outages WHERE locality_id=$1", locality_id)
    return {r["uid"] for r in rows}


async def list_for_locality(locality_id: int, upcoming_only: bool = True) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if upcoming_only:
            rows = await conn.fetch(
                "SELECT * FROM planned_outages WHERE locality_id=$1 AND end_at >= now() "
                "ORDER BY start_at", locality_id)
        else:
            rows = await conn.fetch(
                "SELECT * FROM planned_outages WHERE locality_id=$1 ORDER BY start_at DESC", locality_id)
    out = []
    for r in rows:
        out.append({
            "uid": r["uid"], "distributor": r["distributor"], "number": r["number"],
            "start": r["start_at"].isoformat(), "end": r["end_at"].isoformat(),
            "locations": r["locations"],
        })
    return out


async def prune_old(days: int = 3) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM planned_outages WHERE end_at < now() - ($1 || ' days')::interval", str(days))
