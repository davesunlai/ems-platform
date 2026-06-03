"""Mapování Goodwe sensor ID -> kanonická veličina.

DŮLEŽITÉ: konkrétní sensor ID se mezi rodinami (ET vs DT) i verzemi
firmware/knihovny mírně liší. Proto u každé veličiny zkoušíme seznam
KANDIDÁTŮ a vezmeme první, který je v datech přítomen.

Toto mapování je nutné OVĚŘIT proti reálnému měniči pomocí
`python scripts/discover.py <ip>`, který vypíše všechna dostupná
sensor ID, jejich názvy a hodnoty. Pak se sem případně doplní/opraví.
"""
from __future__ import annotations

from ems.core.model import Metric

# kanonická veličina -> uspořádaný seznam kandidátních Goodwe sensor ID
GOODWE_METRIC_MAP: dict[Metric, list[str]] = {
    Metric.PV_POWER:        ["ppv", "ppv_total", "ppv1"],
    Metric.BATTERY_POWER:   ["pbattery1", "battery_power", "pbattery"],
    Metric.BATTERY_SOC:     ["battery_soc"],
    Metric.GRID_POWER:      ["meter_active_power_total", "active_power_total", "pgrid", "active_power"],
    Metric.LOAD_POWER:      ["house_consumption", "load_power"],
    Metric.ACTIVE_POWER:    ["total_inverter_power", "active_power"],
    Metric.ENERGY_PV_TOTAL: ["e_total"],
    Metric.ENERGY_IMPORT:   ["meter_e_total_imp", "e_total_imp"],
    Metric.ENERGY_EXPORT:   ["meter_e_total_exp", "e_total_exp"],
    Metric.FREQUENCY:       ["fgrid", "grid_frequency", "fgrid1"],
    Metric.TEMPERATURE:     ["temperature", "temperature_air"],
}
