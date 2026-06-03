"""DB vrstva pro uživatele. Sdílí connection pool s API."""
from __future__ import annotations

import logging
import os

from ems.api.db import get_pool
from .security import hash_password

logger = logging.getLogger("ems.auth")


async def ensure_schema() -> None:
    """Idempotentně vytvoří tabulku users (funguje i na existující DB)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'viewer',
                active        BOOLEAN NOT NULL DEFAULT TRUE,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


async def seed_admin() -> None:
    """Vytvoří výchozího admina, pokud žádný uživatel neexistuje."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM users")
        if count and count > 0:
            return
        username = os.getenv("EMS_ADMIN_USER", "admin")
        password = os.getenv("EMS_ADMIN_PASSWORD", "admin")
        await conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES ($1, $2, 'admin')",
            username, hash_password(password),
        )
        logger.warning("Vytvořen výchozí admin '%s'. ZMĚŇ HESLO po prvním přihlášení.", username)


async def get_user(username: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, password_hash, role, active FROM users WHERE username = $1",
            username,
        )
    return dict(row) if row else None


async def list_users() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, username, role, active FROM users ORDER BY id")
    return [dict(r) for r in rows]


async def create_user(username: str, password: str, role: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (username, password_hash, role) VALUES ($1, $2, $3)
            RETURNING id, username, role, active
            """,
            username, hash_password(password), role,
        )
    return dict(row)


async def update_user(user_id: int, *, password: str | None, role: str | None, active: bool | None) -> dict | None:
    sets, args = [], []
    if password is not None:
        args.append(hash_password(password)); sets.append(f"password_hash = ${len(args)}")
    if role is not None:
        args.append(role); sets.append(f"role = ${len(args)}")
    if active is not None:
        args.append(active); sets.append(f"active = ${len(args)}")
    if not sets:
        return None
    args.append(user_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE users SET {', '.join(sets)} WHERE id = ${len(args)} "
            f"RETURNING id, username, role, active",
            *args,
        )
    return dict(row) if row else None


async def delete_user(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    return res.endswith("1")
