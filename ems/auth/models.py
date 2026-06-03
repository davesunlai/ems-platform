"""Modely a oprávnění pro identitu a RBAC.

Role nesou sady oprávnění. Klíčové je oddělení read vs control — to je
bezpečnostní hranice (monitoring vs. řízení) z architektury, ne jen
přístup na stránku. Model je připravený na pozdější granulární práva.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Role(str, Enum):
    VIEWER = "viewer"        # jen čtení telemetrie
    OPERATOR = "operator"    # čtení + řízení (zápis povelů)
    ADMIN = "admin"          # vše + správa uživatelů a modulů


# Oprávnění (permission stringy). Kontroly v API se ptají na tyto.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    Role.VIEWER.value:   {"read"},
    Role.OPERATOR.value: {"read", "control"},
    Role.ADMIN.value:    {"read", "control", "admin"},
}


class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    permissions: list[str]


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    active: bool
    email: str | None = None
    full_name: str | None = None


class UserCreate(BaseModel):
    username: str
    password: str
    role: Role = Role.VIEWER
    email: str | None = None
    full_name: str | None = None


class UserUpdate(BaseModel):
    password: str | None = None
    role: Role | None = None
    active: bool | None = None
    email: str | None = None
    full_name: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
