"""Endpointy: přihlášení, profil, správa uživatelů."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from . import db
from .deps import get_current_user, require_permission
from .models import (
    LoginRequest, ROLE_PERMISSIONS, Token, UserCreate, UserOut, UserUpdate,
)
from .security import create_token, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


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
    return {"username": user["username"], "role": user["role"], "permissions": sorted(user["permissions"])}


@router.get("/admin/users", response_model=list[UserOut])
async def get_users(_: dict = Depends(require_permission("admin"))):
    return await db.list_users()


@router.post("/admin/users", response_model=UserOut, status_code=201)
async def post_user(body: UserCreate, _: dict = Depends(require_permission("admin"))):
    if await db.get_user(body.username):
        raise HTTPException(status_code=409, detail="Uživatel už existuje")
    return await db.create_user(body.username, body.password, body.role.value)


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def patch_user(user_id: int, body: UserUpdate, _: dict = Depends(require_permission("admin"))):
    updated = await db.update_user(
        user_id,
        password=body.password,
        role=body.role.value if body.role else None,
        active=body.active,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Uživatel nenalezen nebo nic ke změně")
    return updated


@router.delete("/admin/users/{user_id}", status_code=204)
async def remove_user(user_id: int, _: dict = Depends(require_permission("admin"))):
    if not await db.delete_user(user_id):
        raise HTTPException(status_code=404, detail="Uživatel nenalezen")
