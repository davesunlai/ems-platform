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
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS note TEXT")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS theme TEXT DEFAULT 'midnight'")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS theme_custom JSONB")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS theme_saved JSONB")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS password_resets (
                token_hash TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
            "SELECT id, username, password_hash, role, active, email, full_name, phone, note, theme, theme_custom, theme_saved FROM users WHERE username = $1",
            username,
        )
    return dict(row) if row else None


async def list_users() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, username, role, active, email, full_name, phone, note FROM users ORDER BY id")
    return [dict(r) for r in rows]


async def create_user(username: str, password: str, role: str,
                      email: str | None = None, full_name: str | None = None,
                      phone: str | None = None, note: str | None = None) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (username, password_hash, role, email, full_name, phone, note)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, username, role, active, email, full_name, phone, note
            """,
            username, hash_password(password), role, email, full_name, phone, note,
        )
    return dict(row)


async def update_user(user_id: int, *, password: str | None = None, role: str | None = None,
                      active: bool | None = None, email: str | None = None,
                      full_name: str | None = None, phone: str | None = None,
                      note: str | None = None, _email_set: bool = False,
                      _name_set: bool = False) -> dict | None:
    sets, args = [], []
    if password is not None:
        args.append(hash_password(password)); sets.append(f"password_hash = ${len(args)}")
    if role is not None:
        args.append(role); sets.append(f"role = ${len(args)}")
    if active is not None:
        args.append(active); sets.append(f"active = ${len(args)}")
    if _email_set:
        args.append(email); sets.append(f"email = ${len(args)}")
    if _name_set:
        args.append(full_name); sets.append(f"full_name = ${len(args)}")
    if phone is not None:
        args.append(phone); sets.append(f"phone = ${len(args)}")
    if note is not None:
        args.append(note); sets.append(f"note = ${len(args)}")
    if not sets:
        return None
    args.append(user_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE users SET {', '.join(sets)} WHERE id = ${len(args)} "
            f"RETURNING id, username, role, active, email, full_name, phone, note",
            *args,
        )
    return dict(row) if row else None


async def delete_user(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    return res.endswith("1")


async def get_user_by_id(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, role, active, email, full_name FROM users WHERE id = $1",
            user_id,
        )
    return dict(row) if row else None


async def get_user_by_email(email: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, role, active, email, full_name FROM users "
            "WHERE lower(email) = lower($1)",
            email,
        )
    return dict(row) if row else None


async def set_theme(user_id: int, theme: str, custom: dict | None, saved=None) -> None:
    import json as _json
    pool = await get_pool()
    async with pool.acquire() as conn:
        if saved is None:
            await conn.execute(
                "UPDATE users SET theme = $1, theme_custom = $2::jsonb WHERE id = $3",
                theme, _json.dumps(custom) if custom is not None else None, user_id)
        else:
            await conn.execute(
                "UPDATE users SET theme = $1, theme_custom = $2::jsonb, theme_saved = $3::jsonb WHERE id = $4",
                theme, _json.dumps(custom) if custom is not None else None, _json.dumps(saved), user_id)


async def set_password(user_id: int, password: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "UPDATE users SET password_hash = $1 WHERE id = $2",
            hash_password(password), user_id,
        )
    return res.endswith("1")


async def create_reset(user_id: int, token_hash: str, expires_at) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO password_resets (token_hash, user_id, expires_at) VALUES ($1, $2, $3)",
            token_hash, user_id, expires_at,
        )


async def get_reset(token_hash: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, expires_at FROM password_resets WHERE token_hash = $1", token_hash
        )
    return dict(row) if row else None


async def delete_reset(token_hash: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM password_resets WHERE token_hash = $1", token_hash)
