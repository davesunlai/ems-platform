"""Model nastavení spínání suchého kontaktu dle SOC."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ContactSettings(BaseModel):
    enabled: bool | None = None
    upper_soc: int | None = Field(default=None, ge=0, le=100)   # horní mez — sepnout
    lower_soc: int | None = Field(default=None, ge=0, le=100)   # dolní mez — rozepnout
