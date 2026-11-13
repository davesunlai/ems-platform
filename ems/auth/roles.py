"""Vlastní role (user1, user2, …): základní práva (viewer/operator/admin) + seznam SKRYTÝCH prvků UI.
Klíče prvků definuje frontend (web/src/uiCatalog.js); backend je jen ukládá a vrací.
Cache v paměti — require_permission je synchronní lookup na každý request."""
from __future__ import annotations

import json
import logging

from ems.api.db import get_pool
from .models import ROLE_PERMISSIONS

logger = logging.getLogger(__name__)
_CACHE: dict[str, dict] = {}   # name -> {"base": str, "hidden": [str]}


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS custom_roles (
                 name TEXT PRIMARY KEY,
                 base TEXT NOT NULL DEFAULT 'viewer',
                 hidden JSONB NOT NULL DEFAULT '[]'::jsonb,
                 created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        # rozhraní dashboardu podle role: flow (schéma TERA) | lcd (panel měniče) — v1.10.0
        await conn.execute("ALTER TABLE custom_roles ADD COLUMN IF NOT EXISTS dashboard_layout TEXT NOT NULL DEFAULT 'flow'")
        # výchozí role „LCD“ (zadání 13. 11.: brácha a uživatelé zvyklí na displej měniče)
        await conn.execute("INSERT INTO custom_roles (name, base, hidden, dashboard_layout) VALUES ('LCD', 'viewer', '[]'::jsonb, 'lcd') ON CONFLICT (name) DO NOTHING")
    await reload()


async def reload() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name, base, hidden, dashboard_layout FROM custom_roles ORDER BY name")
    _CACHE.clear()
    for r in rows:
        h = r["hidden"]
        if isinstance(h, str):
            h = json.loads(h)
        _CACHE[r["name"]] = {"base": r["base"], "hidden": list(h or []), "dashboard_layout": r["dashboard_layout"] or "flow"}
    logger.info("Vlastní role načteny: %s", list(_CACHE) or "žádné")


def permissions_for(role: str) -> set[str]:
    if role in ROLE_PERMISSIONS:
        return ROLE_PERMISSIONS[role]
    c = _CACHE.get(role)
    return ROLE_PERMISSIONS.get(c["base"], set()) if c else set()


LAYOUTS = ("flow", "lcd")


def layout_for(role: str) -> str:
    c = _CACHE.get(role)
    return (c or {}).get("dashboard_layout") or "flow"


def hidden_for(role: str) -> list[str]:
    c = _CACHE.get(role)
    return list(c["hidden"]) if c else []


def is_known_role(role: str) -> bool:
    return role in ROLE_PERMISSIONS or role in _CACHE


def list_roles() -> list[dict]:
    return [{"name": n, "base": c["base"], "hidden": c["hidden"], "dashboard_layout": c.get("dashboard_layout", "flow"), "custom": True} for n, c in _CACHE.items()]


async def upsert(name: str, base: str, hidden: list[str], dashboard_layout: str = "flow") -> dict:
    name = name.strip()
    if not name or name in ROLE_PERMISSIONS:
        raise ValueError("neplatné jméno role (vestavěné viewer/operator/admin nelze přepsat)")
    if base not in ROLE_PERMISSIONS:
        raise ValueError("base musí být viewer / operator / admin")
    if dashboard_layout not in LAYOUTS:
        raise ValueError("dashboard_layout musí být flow / lcd")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO custom_roles (name, base, hidden, dashboard_layout) VALUES ($1, $2, $3::jsonb, $4) "
            "ON CONFLICT (name) DO UPDATE SET base = EXCLUDED.base, hidden = EXCLUDED.hidden, dashboard_layout = EXCLUDED.dashboard_layout",
            name, base, json.dumps(sorted(set(hidden or []))), dashboard_layout)
    await reload()
    return {"name": name, "base": base, "hidden": _CACHE[name]["hidden"], "dashboard_layout": dashboard_layout, "custom": True}


async def delete(name: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM users WHERE role = $1", name)
        if n:
            raise ValueError(f"roli používá {n} uživatel(ů) — nejdřív je přeřaď")
        await conn.execute("DELETE FROM custom_roles WHERE name = $1", name)
    await reload()
