"""Endpointy: přihlášení, profil, změna/reset hesla, správa uživatelů."""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ems.notify.email import send_email, smtp_configured
from . import db
from .deps import get_current_user, require_permission
from .models import (
    ChangePasswordRequest, ForgotPasswordRequest, LoginRequest, ResetPasswordRequest,
    ROLE_PERMISSIONS, Token, UserCreate, UserOut, UserUpdate,
)
from .security import create_token, verify_password

logger = logging.getLogger("ems.auth")
router = APIRouter(prefix="/api", tags=["auth"])

RESET_TTL_HOURS = 1


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/auth/login", response_model=Token)
async def login(body: LoginRequest):
    user = await db.get_user(body.username)
    if not user or not user["active"] or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Špatné jméno nebo heslo")
    role = user["role"]
    return Token(
        access_token=create_token(user["username"], role),
        role=role,
        permissions=sorted(ROLE_PERMISSIONS.get(role, set())),
    )


@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    full = await db.get_user(user["username"])
    return {
        "username": user["username"], "role": user["role"],
        "permissions": sorted(user["permissions"]),
        "email": full.get("email") if full else None,
        "full_name": full.get("full_name") if full else None,
    }


@router.post("/auth/change-password")
async def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    full = await db.get_user(user["username"])
    if not full or not verify_password(body.old_password, full["password_hash"]):
        raise HTTPException(status_code=400, detail="Staré heslo nesouhlasí")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Nové heslo musí mít aspoň 6 znaků")
    await db.set_password(full["id"], body.new_password)
    if full.get("email") and smtp_configured():
        try:
            await send_email(full["email"], "EMS — heslo bylo změněno",
                             f"Dobrý den,\n\nheslo k vašemu účtu '{full['username']}' "
                             f"v EMS Platform bylo právě změněno.\n\nPokud jste to nebyl(a) vy, "
                             f"kontaktujte správce.\n")
        except Exception as exc:
            logger.warning("Notifikace o změně hesla selhala: %s", exc)
    return {"detail": "Heslo změněno"}


@router.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    # Vždy vrať 200 (neprozrazuj, které e-maily existují).
    user = await db.get_user_by_email(body.email)
    if user and user["active"]:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=RESET_TTL_HOURS)
        await db.create_reset(user["id"], _hash_token(token), expires)
        base = os.getenv("EMS_BASE_URL", "http://localhost:8080").rstrip("/")
        link = f"{base}/reset?token={token}"
        if smtp_configured():
            try:
                await send_email(
                    user["email"], "EMS — obnova hesla",
                    f"Dobrý den,\n\npro nastavení nového hesla k účtu '{user['username']}' "
                    f"otevřete tento odkaz (platí {RESET_TTL_HOURS} h):\n\n{link}\n\n"
                    f"Pokud jste o obnovu nežádal(a), tento e-mail ignorujte.\n",
                )
            except Exception as exc:
                logger.warning("Odeslání reset e-mailu selhalo: %s", exc)
        else:
            logger.warning("SMTP není nakonfigurováno — reset e-mail neodeslán.")
    return {"detail": "Pokud e-mail existuje, poslali jsme odkaz pro obnovu hesla."}


@router.post("/auth/reset-password")
async def reset_password(body: ResetPasswordRequest):
    rec = await db.get_reset(_hash_token(body.token))
    if not rec:
        raise HTTPException(status_code=400, detail="Neplatný nebo použitý odkaz")
    expires = rec["expires_at"]
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        await db.delete_reset(_hash_token(body.token))
        raise HTTPException(status_code=400, detail="Odkaz vypršel, požádejte o nový")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Nové heslo musí mít aspoň 6 znaků")
    await db.set_password(rec["user_id"], body.new_password)
    await db.delete_reset(_hash_token(body.token))
    return {"detail": "Heslo nastaveno, můžete se přihlásit."}


@router.get("/admin/users", response_model=list[UserOut])
async def get_users(_: dict = Depends(require_permission("admin"))):
    return await db.list_users()


@router.post("/admin/users", response_model=UserOut, status_code=201)
async def post_user(body: UserCreate, _: dict = Depends(require_permission("admin"))):
    if await db.get_user(body.username):
        raise HTTPException(status_code=409, detail="Uživatel už existuje")
    return await db.create_user(body.username, body.password, body.role.value,
                                email=body.email, full_name=body.full_name,
                                phone=body.phone, note=body.note)


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def patch_user(user_id: int, body: UserUpdate, _: dict = Depends(require_permission("admin"))):
    sent = body.model_fields_set
    updated = await db.update_user(
        user_id,
        password=body.password,
        role=body.role.value if body.role else None,
        active=body.active,
        email=body.email, _email_set="email" in sent,
        full_name=body.full_name, _name_set="full_name" in sent,
        phone=body.phone if "phone" in sent else None,
        note=body.note if "note" in sent else None,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Uživatel nenalezen nebo nic ke změně")
    return updated


@router.delete("/admin/users/{user_id}", status_code=204)
async def remove_user(user_id: int, _: dict = Depends(require_permission("admin"))):
    if not await db.delete_user(user_id):
        raise HTTPException(status_code=404, detail="Uživatel nenalezen")
