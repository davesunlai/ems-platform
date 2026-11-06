"""Bateriové bloky měniče (B1, B2, …): jmenovitá kapacita a popis každého bloku (= bateriový vstup měniče).
Součet bloků = celková kapacita → zapisuje se do planner_config.capacity_kwh lokality, aby zbytek EMS počítal jako dřív.
Bez zadaných bloků se celková kapacita dělí rovnoměrně podle počtu packů, které hlásí měnič."""
from __future__ import annotations

import logging

from ems.api.db import get_pool

logger = logging.getLogger("ems.battest.blocks")

FIELDS = ("name", "capacity_kwh", "modules_count", "module_model", "module_kwh", "cells_per_module", "installed", "note")


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS battery_blocks (
                id SERIAL PRIMARY KEY,
                module_id TEXT NOT NULL,
                idx INTEGER NOT NULL,                 -- 1 = B1 (battery_*_1), 2 = B2 …
                name TEXT,
                capacity_kwh REAL NOT NULL,
                modules_count INTEGER,                -- počet bateriových modulů v bloku
                module_model TEXT,                    -- např. Pylontech H48050
                module_kwh REAL,                      -- jmenovitá kapacita jednoho modulu
                cells_per_module INTEGER,
                installed TEXT,                       -- rok / datum instalace nebo „cca 3 roky“
                note TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (module_id, idx))""")


async def list_blocks(module_id: str) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM battery_blocks WHERE module_id=$1 ORDER BY idx", module_id)
    out = []
    for r in rows:
        d = dict(r); d["updated_at"] = d["updated_at"].isoformat(); out.append(d)
    return out


async def save_blocks(module_id: str, blocks: list[dict]) -> list[dict]:
    """Nahradí bloky modulu zadaným seznamem (idx 1..n podle pořadí) a propíše součet do plánovače lokality."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM battery_blocks WHERE module_id=$1", module_id)
            for i, b in enumerate(blocks, start=1):
                cap = float(b.get("capacity_kwh") or 0)
                if cap <= 0 and b.get("modules_count") and b.get("module_kwh"):
                    cap = float(b["modules_count"]) * float(b["module_kwh"])
                await conn.execute(
                    "INSERT INTO battery_blocks (module_id, idx, name, capacity_kwh, modules_count, module_model, module_kwh, cells_per_module, installed, note) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                    module_id, i, (b.get("name") or f"B{i}").strip(), cap,
                    int(b["modules_count"]) if b.get("modules_count") not in (None, "") else None,
                    (b.get("module_model") or None), float(b["module_kwh"]) if b.get("module_kwh") not in (None, "") else None,
                    int(b["cells_per_module"]) if b.get("cells_per_module") not in (None, "") else None,
                    (b.get("installed") or None), (b.get("note") or None))
        loc = await conn.fetchval("SELECT locality_id FROM modules WHERE id=$1", module_id)
    out = await list_blocks(module_id)
    total = sum(float(b["capacity_kwh"]) for b in out)
    if loc and total > 0:
        try:
            from ems.planner import db as planner_db
            await planner_db.upsert_config(int(loc), {"capacity_kwh": round(total, 2)})
        except Exception as exc:
            logger.warning("bloky → plánovač capacity_kwh: %s", exc)
    return out


async def blocks_for_test(module_id: str, total_kwh: float, packs: int) -> list[dict]:
    """Bloky pro parametry testu: zadané, nebo rovnoměrně rozdělená celková kapacita podle počtu packů měniče."""
    bl = await list_blocks(module_id)
    if bl:
        return [{"idx": b["idx"], "name": b["name"], "capacity_kwh": float(b["capacity_kwh"]), "modules_count": b.get("modules_count"),
                 "module_model": b.get("module_model"), "installed": b.get("installed"), "note": b.get("note")} for b in bl]
    n = max(1, int(packs or 1))
    return [{"idx": i, "name": f"B{i}", "capacity_kwh": round(total_kwh / n, 3), "derived": True} for i in range(1, n + 1)]
