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
    HEAT_PUMP = "heat_pump"     # tepelné čerpadlo (teplo × elektřina, vlastní sémantika)
    SENSOR = "sensor"           # čistě měřicí zařízení (teploty AKU z UVR/CMI apod.), bez řízení
    EV_CHARGER = "ev_charger"   # wallbox (modulovaná odložitelná zátěž; go-e Charger)


class Metric(str, Enum):
    """Měřené veličiny v kanonickém modelu. Jednotky viz UNIT_OF."""
    PV_POWER = "pv_power"
    INVERTER_STATE = "inverter_state"     # stavové slovo měniče (Solis 33095; 4121 = interní override)
    INVERTER_FAULT = "inverter_fault"     # první nenulový fault registr (Solis 33116+), 0 = bez chyby
    ACTIVE_POWER = "active_power"
    REACTIVE_POWER = "reactive_power"
    BATTERY_POWER = "battery_power"
    BATTERY_SOC = "battery_soc"
    BATTERY_SOC_1 = "battery_soc_1"
    BATTERY_SOC_2 = "battery_soc_2"
    BATTERY_VOLTAGE_1 = "battery_voltage_1"
    BATTERY_VOLTAGE_2 = "battery_voltage_2"
    BATTERY_CURRENT_1 = "battery_current_1"
    BATTERY_CURRENT_2 = "battery_current_2"
    BATTERY_POWER_1 = "battery_power_1"
    BATTERY_POWER_2 = "battery_power_2"
    HOUSE_LOAD_INV = "house_load_inv"          # zátěž domu podle měniče (křížová kontrola dopočtu)
    BATTERY_POWER_INV = "battery_power_inv"    # výkon baterie podle měniče (křížová kontrola V×I)
    # 🔬 Diagnostika MPPT (Solis 33049–33056, čteno zdarma v bloku SYS1; ukládá se jen po dobu
    # zapnuté diagnostiky modulu — params.mppt_diag_until)
    PV_VOLTAGE_1 = "pv_voltage_1"
    PV_CURRENT_1 = "pv_current_1"
    PV_POWER_1 = "pv_power_1"
    PV_VOLTAGE_2 = "pv_voltage_2"
    PV_CURRENT_2 = "pv_current_2"
    PV_POWER_2 = "pv_power_2"
    PV_VOLTAGE_3 = "pv_voltage_3"
    PV_CURRENT_3 = "pv_current_3"
    PV_POWER_3 = "pv_power_3"
    PV_VOLTAGE_4 = "pv_voltage_4"
    PV_CURRENT_4 = "pv_current_4"
    PV_POWER_4 = "pv_power_4"
    # 🔋 BMS články (Solis blok 34345–34392, sken 16. 10. 2026): per pack min/max napětí článku,
    # min/max teplota, číslo článku s min/max, proud BMS, cykly, počty modulů/článků. Ukládá se 1×/min.
    BATTERY_CELL_VMIN_1 = "battery_cell_vmin_1"
    BATTERY_CELL_VMAX_1 = "battery_cell_vmax_1"
    BATTERY_CELL_TMIN_1 = "battery_cell_tmin_1"
    BATTERY_CELL_TMAX_1 = "battery_cell_tmax_1"
    BATTERY_CELL_NMIN_1 = "battery_cell_nmin_1"
    BATTERY_CELL_NMAX_1 = "battery_cell_nmax_1"
    BATTERY_BMS_CURRENT_1 = "battery_bms_current_1"
    BATTERY_CYCLES_1 = "battery_cycles_1"
    BATTERY_BMS_MODULES_1 = "battery_bms_modules_1"
    BATTERY_BMS_CELLS_PER_MODULE_1 = "battery_bms_cells_per_module_1"
    BATTERY_CELL_VMIN_2 = "battery_cell_vmin_2"
    BATTERY_CELL_VMAX_2 = "battery_cell_vmax_2"
    BATTERY_CELL_TMIN_2 = "battery_cell_tmin_2"
    BATTERY_CELL_TMAX_2 = "battery_cell_tmax_2"
    BATTERY_CELL_NMIN_2 = "battery_cell_nmin_2"
    BATTERY_CELL_NMAX_2 = "battery_cell_nmax_2"
    BATTERY_BMS_CURRENT_2 = "battery_bms_current_2"
    BATTERY_CYCLES_2 = "battery_cycles_2"
    BATTERY_BMS_MODULES_2 = "battery_bms_modules_2"
    BATTERY_BMS_CELLS_PER_MODULE_2 = "battery_bms_cells_per_module_2"
    ENERGY_BAT_CHARGE_TODAY = "energy_bat_charge_today"
    ENERGY_BAT_DISCHARGE_TODAY = "energy_bat_discharge_today"
    ENERGY_IMPORT_TODAY = "energy_import_today"
    ENERGY_EXPORT_TODAY = "energy_export_today"
    ENERGY_LOAD_TODAY = "energy_load_today"
    ENERGY_BAT_CHARGE_TOTAL = "energy_bat_charge_total"
    ENERGY_BAT_DISCHARGE_TOTAL = "energy_bat_discharge_total"
    ENERGY_IMPORT_TOTAL = "energy_import_total"
    ENERGY_EXPORT_TOTAL = "energy_export_total"
    ENERGY_LOAD_TOTAL = "energy_load_total"
    # Zálohovaný výstup (backup/EPS) Solisu: 33148 výkon, 33153–33158 U/I po fázích (v bloku BAT1 zdarma)
    BACKUP_LOAD_POWER = "backup_load_power"
    BACKUP_VOLTAGE_L1 = "backup_voltage_l1"
    BACKUP_CURRENT_L1 = "backup_current_l1"
    BACKUP_VOLTAGE_L2 = "backup_voltage_l2"
    BACKUP_CURRENT_L2 = "backup_current_l2"
    BACKUP_VOLTAGE_L3 = "backup_voltage_l3"
    BACKUP_CURRENT_L3 = "backup_current_l3"
    # ⚡ Elektroměr (CT) po fázích (33251–33282, sken 13. 11. 2026) — 1×/min
    METER_VOLTAGE_L1 = "meter_voltage_l1"
    METER_VOLTAGE_L2 = "meter_voltage_l2"
    METER_VOLTAGE_L3 = "meter_voltage_l3"
    METER_CURRENT_L1 = "meter_current_l1"
    METER_CURRENT_L2 = "meter_current_l2"
    METER_CURRENT_L3 = "meter_current_l3"
    METER_POWER_L1 = "meter_power_l1"
    METER_POWER_L2 = "meter_power_l2"
    METER_POWER_L3 = "meter_power_l3"
    METER_APPARENT_L1 = "meter_apparent_l1"
    METER_APPARENT_L2 = "meter_apparent_l2"
    METER_APPARENT_L3 = "meter_apparent_l3"
    METER_FREQUENCY = "meter_frequency"
    # Energetické čítače měniče (33161–33180): dnes / celkem — křížová kontrola dopočtů. 1×/min.
    INVERTER_AC_POWER = "inverter_ac_power"    # AC výkon měniče
    INVERTER_CURRENT_L1 = "inverter_current_l1"
    INVERTER_CURRENT_L2 = "inverter_current_l2"
    INVERTER_CURRENT_L3 = "inverter_current_l3"
    BATTERY_SOH_1 = "battery_soh_1"
    BATTERY_SOH_2 = "battery_soh_2"
    BATTERY_TEMP_1 = "battery_temp_1"
    BATTERY_TEMP_2 = "battery_temp_2"
    ENERGY_TODAY = "energy_today"
    GRID_VOLTAGE_L1 = "grid_voltage_l1"
    GRID_VOLTAGE_L2 = "grid_voltage_l2"
    GRID_VOLTAGE_L3 = "grid_voltage_l3"
    GRID_POWER = "grid_power"
    LOAD_POWER = "load_power"
    ENERGY_PV_TOTAL = "energy_pv_total"
    ENERGY_IMPORT = "energy_import"
    ENERGY_EXPORT = "energy_export"
    VOLTAGE = "voltage"
    CURRENT = "current"
    FREQUENCY = "frequency"
    TEMPERATURE = "temperature"
    # --- Teploty akumulačních nádrží (UVR/CMI). Master = 3 zóny, slave = 2 zóny. ---
    TANK_M_TOP = "tank_m_top"     # master horní (I3) – užitná voda, T_min
    TANK_M_MID = "tank_m_mid"     # master střed (I2) – proxy stavu TČ
    TANK_M_BOT = "tank_m_bot"     # master dolní (I1)
    TANK_S_TOP = "tank_s_top"     # slave horní (I4)
    TANK_S_BOT = "tank_s_bot"     # slave dolní (I5) – T_max (STOP spirály)
    TEMP_AMBIENT = "temp_ambient" # technická místnost (I14) – ambient, NE buffer
    AKU_PUMP = "aku_pump"                         # UVR: čerpadlo AKU1↔AKU2 (0/1) — výstup dle params.outputs (default O6)
    UVR_O1 = "uvr_o1"; UVR_O2 = "uvr_o2"; UVR_O3 = "uvr_o3"; UVR_O4 = "uvr_o4"; UVR_O5 = "uvr_o5"   # všechny výstupy UVR (0/1)
    UVR_O6 = "uvr_o6"; UVR_O7 = "uvr_o7"; UVR_O8 = "uvr_o8"; UVR_O9 = "uvr_o9"
    UVR_D10 = "uvr_d10"; UVR_D12 = "uvr_d12"       # digitální vstupy (Jablotron: topení / radiátory)
    # --- Tepelné čerpadlo (Stiebel ISG) ---
    HP_T_OUTDOOR = "hp_t_outdoor"
    HP_T_TANK = "hp_t_tank"                     # reg 508 = „skut. teplota akumulace"
    HP_T_BUFFER = "hp_t_buffer"
    HP_T_BUFFER_SET = "hp_t_buffer_set"
    HP_PRESSURE = "hp_pressure"
    HP_COMPRESSOR = "hp_compressor"             # 0/1
    HP_FAULT = "hp_fault"                       # 0/1 (fault nebo error_code≠0)
    HP_POWER_EST = "hp_power_est"               # odhad příkonu (W), ~nominál při běhu
    HP_EL_HEATING_TODAY = "hp_el_heating_today"     # kWh (celé, ISG)
    HP_EL_DHW_TODAY = "hp_el_dhw_today"
    HP_HEAT_HEATING_TODAY = "hp_heat_heating_today"
    HP_HEAT_DHW_TODAY = "hp_heat_dhw_today"
    # --- Wallbox (go-e Charger, HTTP API v2) ---
    EV_POWER = "ev_power"                       # W — nrg[11]
    EV_CURRENT_L1 = "ev_current_l1"; EV_CURRENT_L2 = "ev_current_l2"; EV_CURRENT_L3 = "ev_current_l3"
    EV_VOLTAGE_L1 = "ev_voltage_l1"; EV_VOLTAGE_L2 = "ev_voltage_l2"; EV_VOLTAGE_L3 = "ev_voltage_l3"
    EV_SESSION_KWH = "ev_session_kwh"           # od připojení auta (wh/1000)
    EV_ENERGY_TOTAL = "ev_energy_total"         # kWh celkem (eto/1000)
    EV_CAR_STATE = "ev_car_state"               # 0 unknown, 1 idle, 2 charging, 3 wait car, 4 complete, 5 error
    EV_AMP_SET = "ev_amp_set"                   # A — náš actuator
    EV_AMP_ALLOWED = "ev_amp_allowed"           # A — acu (efektivně povolený po všech limitech)
    EV_PHASE_MODE = "ev_phase_mode"             # 0 auto, 1 1f, 2 3f
    EV_FORCE = "ev_force"                       # 0 neutral, 1 off, 2 on
    EV_PHASES_ACTIVE = "ev_phases_active"       # pnp
    EV_MODEL_STATUS = "ev_model_status"         # proč (ne)nabíjí
    EV_ERROR = "ev_error"                       # 0 = bez chyby
    EV_TEMP = "ev_temp"                         # °C (max z tma)
    EV_CABLE_LIMIT = "ev_cable_limit"           # A (cbl)


UNIT_OF: dict[Metric, str] = {
    Metric.INVERTER_STATE: "",
    Metric.INVERTER_FAULT: "",
    Metric.PV_POWER: "W",
    Metric.ACTIVE_POWER: "W",
    Metric.REACTIVE_POWER: "var",
    Metric.BATTERY_POWER: "W",
    Metric.BATTERY_SOC: "%",
    Metric.BATTERY_SOC_1: "%",
    Metric.BATTERY_SOC_2: "%",
    Metric.BATTERY_VOLTAGE_1: "V",
    Metric.BATTERY_VOLTAGE_2: "V",
    Metric.BATTERY_CURRENT_1: "A",
    Metric.BATTERY_CURRENT_2: "A",
    Metric.BATTERY_POWER_1: "W",
    Metric.BATTERY_POWER_2: "W",
    Metric.HOUSE_LOAD_INV: "W",
    Metric.BATTERY_POWER_INV: "W",
    Metric.PV_VOLTAGE_1: "V", Metric.PV_CURRENT_1: "A", Metric.PV_POWER_1: "W",
    Metric.PV_VOLTAGE_2: "V", Metric.PV_CURRENT_2: "A", Metric.PV_POWER_2: "W",
    Metric.PV_VOLTAGE_3: "V", Metric.PV_CURRENT_3: "A", Metric.PV_POWER_3: "W",
    Metric.PV_VOLTAGE_4: "V", Metric.PV_CURRENT_4: "A", Metric.PV_POWER_4: "W",
    Metric.METER_VOLTAGE_L1: "V", Metric.METER_VOLTAGE_L2: "V", Metric.METER_VOLTAGE_L3: "V",
    Metric.METER_CURRENT_L1: "A", Metric.METER_CURRENT_L2: "A", Metric.METER_CURRENT_L3: "A",
    Metric.METER_POWER_L1: "W", Metric.METER_POWER_L2: "W", Metric.METER_POWER_L3: "W",
    Metric.METER_APPARENT_L1: "VA", Metric.METER_APPARENT_L2: "VA", Metric.METER_APPARENT_L3: "VA", Metric.METER_FREQUENCY: "Hz",
    Metric.BACKUP_LOAD_POWER: "W", Metric.BACKUP_VOLTAGE_L1: "V", Metric.BACKUP_CURRENT_L1: "A",
    Metric.BACKUP_VOLTAGE_L2: "V", Metric.BACKUP_CURRENT_L2: "A", Metric.BACKUP_VOLTAGE_L3: "V", Metric.BACKUP_CURRENT_L3: "A",
    Metric.BATTERY_CELL_VMIN_1: "V",
    Metric.BATTERY_CELL_VMAX_1: "V",
    Metric.BATTERY_CELL_TMIN_1: "°C",
    Metric.BATTERY_CELL_TMAX_1: "°C",
    Metric.BATTERY_CELL_NMIN_1: "",
    Metric.BATTERY_CELL_NMAX_1: "",
    Metric.BATTERY_BMS_CURRENT_1: "A",
    Metric.BATTERY_CYCLES_1: "",
    Metric.BATTERY_BMS_MODULES_1: "",
    Metric.BATTERY_BMS_CELLS_PER_MODULE_1: "",
    Metric.BATTERY_CELL_VMIN_2: "V",
    Metric.BATTERY_CELL_VMAX_2: "V",
    Metric.BATTERY_CELL_TMIN_2: "°C",
    Metric.BATTERY_CELL_TMAX_2: "°C",
    Metric.BATTERY_CELL_NMIN_2: "",
    Metric.BATTERY_CELL_NMAX_2: "",
    Metric.BATTERY_BMS_CURRENT_2: "A",
    Metric.BATTERY_CYCLES_2: "",
    Metric.BATTERY_BMS_MODULES_2: "",
    Metric.BATTERY_BMS_CELLS_PER_MODULE_2: "",
    Metric.ENERGY_BAT_CHARGE_TODAY: "kWh",
    Metric.ENERGY_BAT_DISCHARGE_TODAY: "kWh",
    Metric.ENERGY_IMPORT_TODAY: "kWh",
    Metric.ENERGY_EXPORT_TODAY: "kWh",
    Metric.ENERGY_LOAD_TODAY: "kWh",
    Metric.ENERGY_BAT_CHARGE_TOTAL: "kWh",
    Metric.ENERGY_BAT_DISCHARGE_TOTAL: "kWh",
    Metric.ENERGY_IMPORT_TOTAL: "kWh",
    Metric.ENERGY_EXPORT_TOTAL: "kWh",
    Metric.ENERGY_LOAD_TOTAL: "kWh",
    Metric.INVERTER_AC_POWER: "W",
    Metric.INVERTER_CURRENT_L1: "A", Metric.INVERTER_CURRENT_L2: "A", Metric.INVERTER_CURRENT_L3: "A",
    Metric.BATTERY_SOH_1: "%",
    Metric.BATTERY_SOH_2: "%",
    Metric.BATTERY_TEMP_1: "°C",
    Metric.BATTERY_TEMP_2: "°C",
    Metric.ENERGY_TODAY: "kWh",
    Metric.GRID_VOLTAGE_L1: "V",
    Metric.GRID_VOLTAGE_L2: "V",
    Metric.GRID_VOLTAGE_L3: "V",
    Metric.GRID_POWER: "W",
    Metric.LOAD_POWER: "W",
    Metric.ENERGY_PV_TOTAL: "kWh",
    Metric.ENERGY_IMPORT: "kWh",
    Metric.ENERGY_EXPORT: "kWh",
    Metric.VOLTAGE: "V",
    Metric.CURRENT: "A",
    Metric.FREQUENCY: "Hz",
    Metric.TEMPERATURE: "°C",
    Metric.TANK_M_TOP: "°C",
    Metric.TANK_M_MID: "°C",
    Metric.TANK_M_BOT: "°C",
    Metric.TANK_S_TOP: "°C",
    Metric.TANK_S_BOT: "°C",
    Metric.TEMP_AMBIENT: "°C",
    Metric.HP_T_OUTDOOR: "°C",
    Metric.HP_T_TANK: "°C",
    Metric.HP_T_BUFFER: "°C",
    Metric.HP_T_BUFFER_SET: "°C",
    Metric.HP_PRESSURE: "bar",
    Metric.HP_COMPRESSOR: "",
    Metric.HP_FAULT: "",
    Metric.HP_POWER_EST: "W",
    Metric.HP_EL_HEATING_TODAY: "kWh",
    Metric.HP_EL_DHW_TODAY: "kWh",
    Metric.HP_HEAT_HEATING_TODAY: "kWh",
    Metric.HP_HEAT_DHW_TODAY: "kWh",
    Metric.EV_POWER: "W",
    Metric.EV_CURRENT_L1: "A", Metric.EV_CURRENT_L2: "A", Metric.EV_CURRENT_L3: "A",
    Metric.EV_VOLTAGE_L1: "V", Metric.EV_VOLTAGE_L2: "V", Metric.EV_VOLTAGE_L3: "V",
    Metric.EV_SESSION_KWH: "kWh", Metric.EV_ENERGY_TOTAL: "kWh",
    Metric.EV_CAR_STATE: "", Metric.EV_AMP_SET: "A", Metric.EV_AMP_ALLOWED: "A",
    Metric.EV_PHASE_MODE: "", Metric.EV_FORCE: "", Metric.EV_PHASES_ACTIVE: "",
    Metric.EV_MODEL_STATUS: "", Metric.EV_ERROR: "", Metric.EV_TEMP: "°C", Metric.EV_CABLE_LIMIT: "A",
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
