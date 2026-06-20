"""Modely lokalit a párovacích vazeb."""
from __future__ import annotations

from datetime import date

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
    cez_ean: str | None = None
    cez_meter: str | None = None
    addr_zip: str | None = None
    addr_city: str | None = None
    addr_street: str | None = None


class AssignUser(BaseModel):
    user_id: int


class AssignDevice(BaseModel):
    module_id: str


class BillingSettings(BaseModel):
    billing_start: date | None = None
    pricing_mode: str | None = None          # 'spot' | 'tariff'
    tariff_import_czk: float | None = None    # Kč/kWh (nákup ze sítě)
    tariff_export_czk: float | None = None    # Kč/kWh (prodej do sítě)
    billing_months: int | None = None
    export_limit_kwh: float | None = None
    alert_enabled: bool | None = None
    autolimit_enabled: bool | None = None
    alert_email: str | None = None
    baseline_export_kwh: float | None = None
    baseline_import_kwh: float | None = None
