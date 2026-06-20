"""DB vrstva registru modulů. Sdílí pool s API/kolektorem."""
from __future__ import annotations

import json
import logging
import os

from ems.api.db import get_pool
from ems.core.model import DeviceType
from .models import Module, ModuleKind

logger = logging.getLogger("ems.modules")


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS modules (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                kind        TEXT NOT NULL DEFAULT 'source_read',
                device_type TEXT NOT NULL DEFAULT 'generation',
                adapter     TEXT NOT NULL,
                params      JSONB NOT NULL DEFAULT '{}',
                region      TEXT NOT NULL DEFAULT 'CZ',
                enabled     BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def _row_to_module(row) -> Module:
    return Module(
        id=row["id"], name=row["name"], kind=row["kind"],
        device_type=row["device_type"], adapter=row["adapter"],
        params=json.loads(row["params"]) if isinstance(row["params"], str) else row["params"],
        region=row["region"], enabled=row["enabled"],
        locality_id=row.get("locality_id"),
    )


async def list_all() -> list[Module]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM modules ORDER BY id")
    return [_row_to_module(r) for r in rows]


async def list_all_with_status() -> list[dict]:
    """Moduly + název lokality + příznak aktivity (čerstvá telemetrie < 5 min)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.*,
                   l.name AS locality,
                   (max(s.time) > now() - interval '5 minutes') AS active,
                   max(s.time) AS last_seen
            FROM modules m
            LEFT JOIN localities l ON l.id = m.locality_id
            LEFT JOIN samples s    ON s.device_id = m.id
            GROUP BY m.id, l.name
            ORDER BY m.id
            """
        )
    out = []
    for r in rows:
        d = _row_to_module(r).model_dump()
        d["device_type"] = d["device_type"].value if hasattr(d["device_type"], "value") else d["device_type"]
        d["kind"] = d["kind"].value if hasattr(d["kind"], "value") else d["kind"]
        d["locality"] = r["locality"]
        d["active"] = bool(r["active"]) if r["active"] is not None else False
        d["last_seen"] = r["last_seen"].isoformat() if r["last_seen"] else None
        out.append(d)
    return out


async def list_enabled_reads() -> list[Module]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM modules WHERE enabled = TRUE AND kind = 'source_read' ORDER BY id"
        )
    return [_row_to_module(r) for r in rows]


async def create(m: Module) -> Module:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO modules (id, name, kind, device_type, adapter, params, region, enabled)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
            RETURNING *
            """,
            m.id, m.name, m.kind.value, m.device_type.value, m.adapter,
            json.dumps(m.params), m.region, m.enabled,
        )
    return _row_to_module(row)


async def update(module_id: str, patch: dict) -> Module | None:
    sets, args = [], []
    for col in ("name", "kind", "device_type", "adapter", "region", "enabled"):
        if patch.get(col) is not None:
            val = patch[col]
            val = val.value if hasattr(val, "value") else val
            args.append(val); sets.append(f"{col} = ${len(args)}")
    if patch.get("params") is not None:
        args.append(json.dumps(patch["params"])); sets.append(f"params = ${len(args)}::jsonb")
    if not sets:
        return None
    args.append(module_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE modules SET {', '.join(sets)} WHERE id = ${len(args)} RETURNING *", *args
        )
    return _row_to_module(row) if row else None


async def delete(module_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM modules WHERE id = $1", module_id)
    return res.endswith("1")


async def seed_from_devices(yaml_path: str) -> None:
    """Při prázdném registru naimportuje zařízení z devices.yaml (migrace)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM modules")
    if n and n > 0:
        return
    if not os.path.exists(yaml_path):
        return
    from ems.collector.config import load_devices
    count = 0
    for d in load_devices(yaml_path):
        await create(Module(
            id=d.id, name=d.name, kind=ModuleKind.SOURCE_READ,
            device_type=d.type, adapter=d.adapter, params=d.params,
            region=d.region, enabled=True,
        ))
        count += 1
    if count:
        logger.warning("Registr modulů naimportován z %s (%d zařízení).", yaml_path, count)


async def get(module_id: str) -> Module | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM modules WHERE id = $1", module_id)
    return _row_to_module(row) if row else None
