"""Modely lokalit a párovacích vazeb."""
from __future__ import annotations

from pydantic import BaseModel


class LocalityCreate(BaseModel):
    name: str
    address: str | None = None
    region: str = "CZ"
    note: str | None = None


class LocalityUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    region: str | None = None
    note: str | None = None


class AssignUser(BaseModel):
    user_id: int


class AssignDevice(BaseModel):
    module_id: str
