"""Modely registru modulů.

Modul = jednotka, kterou systém spravuje. Taxonomie podle směru/účelu:
  - source_read  : čte telemetrii ze zařízení/systému  (funkční nyní)
  - source_write : zapisuje povely do zařízení/systému  (Fáze C)
  - logic        : automatizační logika                  (Fáze D)

Čtecí modul je v podstatě adaptér (goodwe, mock, …) nad konkrétním zařízením.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from ems.core.model import DeviceType


class ModuleKind(str, Enum):
    SOURCE_READ = "source_read"
    SOURCE_WRITE = "source_write"
    LOGIC = "logic"


class Module(BaseModel):
    id: str
    name: str = ""
    kind: ModuleKind = ModuleKind.SOURCE_READ
    device_type: DeviceType = DeviceType.GENERATION
    adapter: str
    params: dict = Field(default_factory=dict)
    region: str = "CZ"
    enabled: bool = True
    locality_id: int | None = None
    emsbox_id: int | None = None
    transport_params: dict | None = None


class ModuleCreate(BaseModel):
    id: str
    name: str = ""
    kind: ModuleKind = ModuleKind.SOURCE_READ
    device_type: DeviceType = DeviceType.GENERATION
    adapter: str
    params: dict = Field(default_factory=dict)
    region: str = "CZ"
    enabled: bool = True


class ModuleUpdate(BaseModel):
    name: str | None = None
    emsbox_id: int | None = None            # NULL/-1 = přímé čtení frantou
    transport_params: dict | None = None    # rtu/tcp/http parametry pro EMSBOX
    kind: ModuleKind | None = None
    device_type: DeviceType | None = None
    adapter: str | None = None
    params: dict | None = None
    region: str | None = None
    enabled: bool | None = None
