"""Konfigurace kolektoru: zařízení z YAML + továrny na adaptéry a sinky."""
from __future__ import annotations

import os

import yaml

from ems.core.interfaces import Sink, TelemetryAdapter
from ems.core.model import Device


def load_devices(path: str) -> list[Device]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return [Device(**d) for d in raw.get("devices", [])]


def build_adapter(device: Device) -> TelemetryAdapter:
    """Vytvoří instanci adaptéru podle device.adapter. Sem se přidávají nové typy."""
    name = device.adapter.lower()
    # Klíče určené jen pro UI/zobrazení — do konstruktoru adaptéru NEPATŘÍ.
    DISPLAY_ONLY = {"hidden_metrics"}
    params = {k: v for k, v in device.params.items() if k not in DISPLAY_ONLY}
    if name == "mock":
        from ems.adapters.goodwe import MockInverterAdapter
        return MockInverterAdapter(device_id=device.id, **params)
    if name == "goodwe":
        from ems.adapters.goodwe import GoodweAdapter
        return GoodweAdapter(device_id=device.id, **params)
    if name == "solis":
        from ems.adapters.solis import SolisAdapter
        # V UI je Modbus jednotka pojmenovaná 'device_id' (=1) — koliduje s EMS
        # device_id (id modulu). Přemapuj na 'unit', ať se nepřepíše.
        if "device_id" in params and "unit" not in params:
            params["unit"] = params.pop("device_id")
        return SolisAdapter(device_id=device.id, device_type=device.type.value, **params)
    raise ValueError(f"Neznámý adaptér '{device.adapter}' pro zařízení '{device.id}'")


def build_sink() -> Sink:
    """Vybere sink podle proměnné prostředí EMS_SINK (stdout | timescale)."""
    kind = os.getenv("EMS_SINK", "stdout").lower()
    if kind == "stdout":
        from ems.sinks.stdout import StdoutSink
        return StdoutSink()
    if kind == "timescale":
        from ems.sinks.timescale import TimescaleSink
        dsn = os.getenv("EMS_DB_DSN", "postgresql://ems:ems@timescaledb:5432/ems")
        return TimescaleSink(dsn)
    raise ValueError(f"Neznámý sink '{kind}' (EMS_SINK)")
