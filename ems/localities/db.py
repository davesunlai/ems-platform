"""DB vrstva lokalit + vazeb uživatel↔lokalita a zařízení↔lokalita.

Model vazeb:
  - lokalita 1:N zařízení (modules.locality_id)
  - uživatel M:N lokalita (user_localities)
"""
from __future__ import annotations

from ems.api.db import get_pool


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS localities (
                id         SERIAL PRIMARY KEY,
                name       TEXT NOT NULL,
                address    TEXT,
                region     TEXT NOT NULL DEFAULT 'CZ',
                note       TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_localities (
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                locality_id INTEGER NOT NULL REFERENCES localities(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, locality_id)
            )
            """
        )
        await conn.execute(
            "ALTER TABLE modules ADD COLUMN IF NOT EXISTS locality_id INTEGER "
            "REFERENCES localities(id) ON DELETE SET NULL"
        )
        await conn.execute(
            "ALTER TABLE user_localities ADD COLUMN IF NOT EXISTS notify BOOLEAN NOT NULL DEFAULT FALSE"
        )
        for col in ("notify_email", "notify_browser"):
            await conn.execute(f"ALTER TABLE user_localities ADD COLUMN IF NOT EXISTS {col} BOOLEAN NOT NULL DEFAULT TRUE")
        await conn.execute("ALTER TABLE user_localities ADD COLUMN IF NOT EXISTS notify_mobile BOOLEAN NOT NULL DEFAULT FALSE")
        # Zúčtovací období (dle ČEZ) + limit přetoků a upozornění
        for col, ddl in (
            ("billing_start", "DATE"),
            ("billing_months", "INTEGER NOT NULL DEFAULT 12"),
            ("export_limit_kwh", "DOUBLE PRECISION"),
            ("alert_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("autolimit_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("alert_email", "TEXT"),
            ("alert_fired", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("limit_applied", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("period_anchor", "DATE"),
            ("baseline_export_kwh", "DOUBLE PRECISION"),
            ("baseline_import_kwh", "DOUBLE PRECISION"),
            ("baseline_period_start", "DATE"),
            ("cez_ean", "TEXT"),
            ("cez_meter", "TEXT"),
            ("addr_zip", "TEXT"),
            ("addr_city", "TEXT"),
            ("addr_street", "TEXT"),
            # Cenění: spot (dle OTE) / tariff (pevná cena). U tarifu cena Kč/kWh.
            ("pricing_mode", "TEXT NOT NULL DEFAULT 'spot'"),
            ("tariff_import_czk", "DOUBLE PRECISION"),
            ("tariff_export_czk", "DOUBLE PRECISION"),
            # Forecast: poloha (Open-Meteo) + celkový instalovaný výkon FVE.
            ("lat", "DOUBLE PRECISION"),
            ("lon", "DOUBLE PRECISION"),
            ("pv_kwp_total", "DOUBLE PRECISION"),
        ):
            await conn.execute(
                f"ALTER TABLE localities ADD COLUMN IF NOT EXISTS {col} {ddl}"
            )


async def set_billing(loc_id: int, patch: dict) -> dict | None:
    if not patch:
        return await get(loc_id)
    cols = ["billing_start", "billing_months", "export_limit_kwh",
            "alert_enabled", "autolimit_enabled", "alert_email",
            "baseline_export_kwh", "baseline_import_kwh", "baseline_period_start",
            "pricing_mode", "tariff_import_czk", "tariff_export_czk"]
    sets, args = [], []
    for k in cols:
        if k in patch:
            args.append(patch[k]); sets.append(f"{k} = ${len(args)}")
    if not sets:
        return await get(loc_id)
    args.append(loc_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE localities SET {', '.join(sets)} WHERE id = ${len(args)} RETURNING *", *args
        )
    return dict(row) if row else None


async def list_all() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM localities ORDER BY name")
    return [dict(r) for r in rows]


async def users_with_email_for_locality(loc_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT u.id, u.username, u.full_name, u.email FROM users u "
            "JOIN user_localities ul ON ul.user_id = u.id "
            "WHERE ul.locality_id = $1 AND u.active = true "
            "AND u.email IS NOT NULL AND u.email <> '' ORDER BY u.username",
            loc_id)
    return [dict(r) for r in rows]


async def localities_for_user(user_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT l.* FROM localities l "
            "JOIN user_localities ul ON ul.locality_id = l.id "
            "WHERE ul.user_id = $1 ORDER BY l.name", user_id)
    return [dict(r) for r in rows]


async def get(loc_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM localities WHERE id = $1", loc_id)
    return dict(row) if row else None


async def create(name: str, address, region: str, note) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO localities (name, address, region, note) VALUES ($1,$2,$3,$4) RETURNING *",
            name, address, region, note,
        )
    return dict(row)


async def update(loc_id: int, patch: dict) -> dict | None:
    sets, args = [], []
    for k in ("name", "address", "region", "note", "cez_ean", "cez_meter", "addr_zip", "addr_city", "addr_street",
              "lat", "lon", "pv_kwp_total"):
        if k in patch and patch[k] is not None:
            args.append(patch[k]); sets.append(f"{k} = ${len(args)}")
    if not sets:
        return await get(loc_id)
    args.append(loc_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE localities SET {', '.join(sets)} WHERE id = ${len(args)} RETURNING *", *args
        )
    return dict(row) if row else None


async def delete(loc_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM localities WHERE id = $1", loc_id)
    return res.endswith("1")


# --- vazby uživatelů ---
async def assign_user(loc_id: int, user_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_localities (user_id, locality_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
            user_id, loc_id,
        )


async def unassign_user(loc_id: int, user_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM user_localities WHERE user_id = $1 AND locality_id = $2", user_id, loc_id
        )


async def browser_localities_for_user(user_id: int) -> list[int]:
    """Lokality, kde má uživatel zapnutou notifikaci i kanál prohlížeč."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT locality_id FROM user_localities WHERE user_id=$1 AND notify=true AND notify_browser=true", user_id)
    return [r["locality_id"] for r in rows]


async def users_for_locality(loc_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT u.id, u.username, u.full_name, ul.notify, ul.notify_email, ul.notify_browser, ul.notify_mobile FROM users u "
            "JOIN user_localities ul ON ul.user_id = u.id WHERE ul.locality_id = $1 ORDER BY u.username",
            loc_id,
        )
    return [dict(r) for r in rows]


async def set_user_notify(loc_id: int, user_id: int, notify: bool,
                          email: bool | None = None, browser: bool | None = None,
                          mobile: bool | None = None) -> None:
    pool = await get_pool()
    sets = ["notify = $3"]
    args = [loc_id, user_id, bool(notify)]
    for val, col in ((email, "notify_email"), (browser, "notify_browser"), (mobile, "notify_mobile")):
        if val is not None:
            args.append(bool(val))
            sets.append(f"{col} = ${len(args)}")
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE user_localities SET {', '.join(sets)} WHERE locality_id = $1 AND user_id = $2", *args)


async def notify_users_for_locality(loc_id: int) -> list[dict]:
    """Uživatelé lokality s zapnutými notifikacemi (aktivní)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT u.id, u.username, u.full_name, u.email, ul.notify_email, ul.notify_browser, ul.notify_mobile FROM users u "
            "JOIN user_localities ul ON ul.user_id = u.id "
            "WHERE ul.locality_id = $1 AND ul.notify = true AND u.active = true ORDER BY u.username",
            loc_id)
    return [dict(r) for r in rows]


# --- vazby zařízení (modulů) ---
async def assign_device(loc_id: int, module_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE modules SET locality_id = $1 WHERE id = $2", loc_id, module_id)


async def unassign_device(module_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE modules SET locality_id = NULL WHERE id = $1", module_id)


async def devices_for_locality(loc_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name FROM modules WHERE locality_id = $1 ORDER BY id", loc_id
        )
    return [dict(r) for r in rows]
