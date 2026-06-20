"""Kanonický (společný) datový model.

Každé zařízení v portfoliu — FVE, baterie, nabíječka, měřicí bod sítě —
mapuje na tyto společné koncepty. Adaptéry překládají nativní protokol
do tohoto modelu; jádro a úložiště už pracují jen s ním.

Znaménkové konvence (drž se jich napříč celým systémem):
  PV_POWER       >= 0
  BATTERY_POWER  + = nabíjení,  - = vybíjení
  GRID_POWER     + = odběr ze sítě (import),  - = dodávka do sítě (export)
  LOAD_POWER     >= 0 (spotřeba)
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceType(str, Enum):
    GENERATION = "generation"   # FVE, VtE, kogenerace, vodní
    STORAGE = "storage"         # BESS, PVE, vodík
    LOAD = "load"               # domácnost, nabíječka, spirály
    GRID_POINT = "grid_point"   # přípojný/měřicí bod
    HYBRID = "hybrid"           # hybridní střídač: FVE + baterie + síť (+ backup) v jednom


class Metric(str, Enum):
    """Měřené veličiny v kanonickém modelu. Jednotky viz UNIT_OF."""
    PV_POWER = "pv_power"
    ACTIVE_POWER = "active_power"
    REACTIVE_POWER = "reactive_power"
    BATTERY_POWER = "battery_power"
    BATTERY_SOC = "battery_soc"
    GRID_POWER = "grid_power"
    LOAD_POWER = "load_power"
    ENERGY_PV_TOTAL = "energy_pv_total"
    ENERGY_IMPORT = "energy_import"
    ENERGY_EXPORT = "energy_export"
    VOLTAGE = "voltage"
    CURRENT = "current"
    FREQUENCY = "frequency"
    TEMPERATURE = "temperature"


UNIT_OF: dict[Metric, str] = {
    Metric.PV_POWER: "W",
    Metric.ACTIVE_POWER: "W",
    Metric.REACTIVE_POWER: "var",
    Metric.BATTERY_POWER: "W",
    Metric.BATTERY_SOC: "%",
    Metric.GRID_POWER: "W",
    Metric.LOAD_POWER: "W",
    Metric.ENERGY_PV_TOTAL: "kWh",
    Metric.ENERGY_IMPORT: "kWh",
    Metric.ENERGY_EXPORT: "kWh",
    Metric.VOLTAGE: "V",
    Metric.CURRENT: "A",
    Metric.FREQUENCY: "Hz",
    Metric.TEMPERATURE: "°C",
}


class Quality(str, Enum):
    GOOD = "good"
    UNCERTAIN = "uncertain"
    BAD = "bad"
    STALE = "stale"


class Measurement(BaseModel):
    metric: Metric
    value: float
    unit: str
    quality: Quality = Quality.GOOD


class Reading(BaseModel):
    """Jeden odečet z jednoho zařízení v jednom okamžiku (více veličin).

    states: kategorické stavy (např. operation_mode = ECO_CHARGE), které
    nejsou číselné metriky — ukládají se zvlášť (poslední hodnota vyhrává).
    """
    device_id: str
    timestamp: datetime = Field(default_factory=utcnow)
    measurements: list[Measurement] = Field(default_factory=list)
    states: dict[str, str] = Field(default_factory=dict)


class Sample(BaseModel):
    """Zploštělý jednotlivý vzorek pro uložení do časové DB (jeden řádek)."""
    time: datetime
    device_id: str
    metric: Metric
    value: float
    unit: str
    quality: Quality = Quality.GOOD


class Device(BaseModel):
    """Statická konfigurace zařízení (kdo to je, kde je, čím se připojit)."""
    id: str
    type: DeviceType
    adapter: str                       # název adaptéru, např. "goodwe" | "mock"
    name: str = ""
    site: str = ""
    region: str = "CZ"
    timezone: str = "Europe/Prague"
    params: dict = Field(default_factory=dict)


def reading_to_samples(reading: Reading) -> list[Sample]:
    """Rozloží Reading na jednotlivé Sample řádky pro úložiště."""
    return [
        Sample(
            time=reading.timestamp,
            device_id=reading.device_id,
            metric=m.metric,
            value=m.value,
            unit=m.unit,
            quality=m.quality,
        )
        for m in reading.measurements
    ]
