"""Mapa čtecích registrů Solis S6-EH3P50K-H (input, FC 0x04).

Adresy jsou "raw" (bez offsetu 30001) a jsou OVĚŘENÉ na reálném kuse —
viz SOLIS-ADAPTER-BRIEF.md §9 (telemetrie) a §10 (dva battery packy).

Každá položka = (adresa, typ, měřítko). Typy: "u16" | "s16" | "u32" | "s32".
U32/S32 se čtou jako count=2 a skládají (hi<<16)|lo.
"""
from __future__ import annotations

# --- Systémové registry (společné pro celý měnič) ---
REG_PV_POWER = (33057, "u32", 1.0)        # W  — celkový DC výkon FVE
# 🔬 MPPT 1–4: DC napětí / proud (standardní Solis mapa, v bloku SYS1 — čtou se zdarma).
# Výkon MPPT = U × I (měnič ho zvlášť nedává). Stringy v rámci MPPT měnič nerozlišuje.
REG_MPPT = {
    1: ((33049, "u16", 0.1), (33050, "u16", 0.1)),
    2: ((33051, "u16", 0.1), (33052, "u16", 0.1)),
    3: ((33053, "u16", 0.1), (33054, "u16", 0.1)),
    4: ((33055, "u16", 0.1), (33056, "u16", 0.1)),
}
REG_ENERGY_TOTAL = (33029, "u32", 1.0)    # kWh — celkem vyrobeno
REG_ENERGY_TODAY = (33035, "u16", 0.1)    # kWh — vyrobeno dnes
# Činný výkon sítě (meter). POZOR: Solis používá + = DO sítě (export),
# − = ZE sítě (import). EMS GRID_POWER je OPAČNĚ (+ = import). Adaptér to otočí.
REG_GRID_METER = (33130, "s32", 1.0)      # W (Solis: +export / −import)
# 3f síťová napětí (ověřeno §9)
REG_GRID_V_L1 = (33073, "u16", 0.1)       # V
REG_GRID_V_L2 = (33074, "u16", 0.1)       # V
REG_GRID_V_L3 = (33075, "u16", 0.1)       # V
REG_INV_TEMP = (33093, "s16", 0.1)        # °C — teplota měniče
# Křížové kontroly (v bloku BLOCK_SYS2 / BLOCK_BAT1 — čtou se ZDARMA, žádný dotaz navíc):
REG_INV_I_L1 = (33076, "u16", 0.1)         # A  — proud měniče fáze A
REG_INV_I_L2 = (33077, "u16", 0.1)         # A  — proud měniče fáze B
REG_INV_I_L3 = (33078, "u16", 0.1)         # A  — proud měniče fáze C
REG_INV_AC_POWER = (33079, "s32", 1.0)     # W  — činný AC výkon měniče
REG_HOUSE_LOAD = (33147, "u16", 1.0)       # W  — zátěž domu podle měniče
REG_BAT_POWER_INV = (33149, "s32", 1.0)    # W  — výkon baterie podle měniče (manuál: + nabíjení / − vybíjení)

# --- Baterie: dva packy, KAŽDÝ MÁ JINÝ LAYOUT (ne offset!) viz brief §10 ---
# voltage = napětí inv-side (0.1 V), current = proud (0.1 A, + nabíjení / − vybíjení)
BATTERY_PACKS = {
    1: {
        "soc": (33139, "u16", 1.0),
        "voltage": (33133, "u16", 0.1),
        "current": (33134, "s16", 0.1),
        "direction": (33135, "u16", 1.0),   # 0 = nabíjení, 1 = vybíjení (33134 vrací magnitudu!)
        "soh": (33140, "u16", 1.0),
        "temp": (33144, "s16", 0.1),
    },
    2: {
        "soc": (34278, "u16", 1.0),
        "voltage": (34289, "u16", 0.1),
        "current": (34290, "s16", 0.1),   # MAGNITUDA (ověřeno živě 3.9.2026: +2.2 A při vybíjení)
        "direction": (34291, "u16", 1.0), # 0 = nabíjení, 1 = vybíjení — OVĚŘENO živě (34291=1 při vybíjení B2)
        "soh": (34279, "u16", 1.0),
        "temp": (34282, "s16", 0.1),      # 34281 vracelo nesmysl -> alternativa 34282
    },
}

# Bloky pro HROMADNÉ čtení (start, count). Místo ~20 jednotlivých dotazů
# přečteme pár souvislých bloků = mnohem šetrnější k měniči/sticku (jedno
# spojení), který víc rychlých dotazů za sebou nedával (timeouty).
BLOCK_SYS1 = (33029, 30)   # 33029..33058: energie celk./dnes, PV stringy, FVE výkon
BLOCK_SYS2 = (33073, 21)   # 33073..33093: 3f napětí L1-3 + teplota měniče
BLOCK_GRID = (33130, 2)    # 33130..33131: síťový meter (S32)
BLOCK_BAT1 = (33133, 48)   # 33133..33180: baterie 1 + energetické čítače 33161–33180 (zdarma v jednom dotazu)
# Energetické čítače měniče (ověřeno skenem 16. 10. 2026 — sedí na Solis mapu):
REG_E_BAT_CHARGE_TOTAL = (33161, "u32", 1.0)      # kWh nabito do baterie celkem
REG_E_BAT_CHARGE_TODAY = (33163, "u16", 0.1)
REG_E_BAT_DISCHARGE_TOTAL = (33165, "u32", 1.0)
REG_E_BAT_DISCHARGE_TODAY = (33167, "u16", 0.1)
REG_E_IMPORT_TOTAL = (33169, "u32", 1.0)          # odběr ze sítě
REG_E_IMPORT_TODAY = (33171, "u16", 0.1)
REG_E_EXPORT_TOTAL = (33173, "u32", 1.0)          # dodávka do sítě
REG_E_EXPORT_TODAY = (33175, "u16", 0.1)
REG_E_LOAD_TOTAL = (33177, "u32", 1.0)            # spotřeba domu
REG_E_LOAD_TODAY = (33179, "u16", 0.1)
# Zálohovaný výstup (backup/EPS) — sken 16. 10. 2026: 33153/55/57 = 239,7/240,6/223,0 V, proudy 0 (bez zátěže)
REG_BACKUP_LOAD = (33148, "u16", 1.0)       # W — zátěž na backup výstupu
REG_BACKUP = {1: ((33153, "u16", 0.1), (33154, "u16", 0.1)),
              2: ((33155, "u16", 0.1), (33156, "u16", 0.1)),
              3: ((33157, "u16", 0.1), (33158, "u16", 0.1))}
# 🔋 BMS články (sken 16. 10. 2026): dva shodné bloky po 25 reg.; značka 0xAA55 jen na 34345 (a 34414), 34370 = 0.
# pack A = 34345, pack B = 34370. Offsety: +1 konst. 4785, +3 Umin článku (mV), +4 Umax (mV),
# +5 Tmin (×0.1 °C), +6 Tmax, +7 číslo článku s Umin, +9 číslo článku s Umax, +13 proud BMS (×0.1 A),
# +17 cykly, +19 článků/modul (15), +20 modulů (11). Přiřazení A→baterie 1, B→baterie 2 (param bms_swap otočí).
BLOCK_BMS = (34345, 48)
BMS_BASE = {1: 34345, 2: 34370}
BMS_OFF = {"cell_vmin": (3, 0.001), "cell_vmax": (4, 0.001), "cell_tmin": (5, 0.1), "cell_tmax": (6, 0.1),
           "cell_nmin": (7, 1.0), "cell_nmax": (9, 1.0), "bms_current": (13, 0.1), "cycles": (17, 1.0),
           "bms_cells_per_module": (19, 1.0), "bms_modules": (20, 1.0)}
BLOCK_BAT2 = (34275, 17)   # 34275..34291: baterie 2 (vč. směrového registru 34291)

# --- ŘÍDICÍ (holding) registry — FC03 čtení / FC06 zápis. ---
# POZOR: scale a sémantika u 3f 50kW modelu NEPOTVRZENO (brief §11, hodnoty
# z 1f/S5 dokumentace). Před prvním ostrým zápisem ověřit write-probem na
# reálném kuse a testovat na malém výkonu. Některé zápisy jdou do flash.
CTRL_WORK_MODE = 43110               # pracovní režim (bitfield; 0x21 = Self-Use)
CTRL_FORCE = 43135                   # 0 = off, 1 = nucené nabíjení, 2 = nucené vybíjení
CTRL_FORCE_POWER = 43136             # výkon nuceného NABÍJENÍ (jednotka 10 W; kW×100)
CTRL_FORCE_DISCHARGE_POWER = 43129   # výkon nuceného VYBÍJENÍ (jednotka 10 W; kW×100)
CTRL_CHARGE_CURRENT_LIMIT = 43012    # limit nabíjecího proudu (0.1 A)
CTRL_DISCHARGE_CURRENT_LIMIT = 43013 # limit vybíjecího proudu (0.1 A)
CTRL_SOC_BACKUP = 43024              # SOC práh backup
CTRL_SOC_FORCE = 43030              # SOC práh force

# Řídicí registry pro write-probe (přečtení aktuálního stavu, FC03).
CONTROL_REGISTERS = [
    ("force_discharge_power", 43129),   # doplněno 6.9.: v read_controls chyběl —右 při vyšetřování škrcení
    ("Pracovní režim     ", CTRL_WORK_MODE),
    ("Force 0/1/2        ", CTRL_FORCE),
    ("Force výkon        ", CTRL_FORCE_POWER),
    ("Limit nabíj. proudu", CTRL_CHARGE_CURRENT_LIMIT),
    ("Limit vybíj. proudu", CTRL_DISCHARGE_CURRENT_LIMIT),
    ("SOC backup         ", CTRL_SOC_BACKUP),
    ("SOC force          ", CTRL_SOC_FORCE),
]


# Stavový blok (vyšetřování 6.–7. 9. 2026): 33095 = stavové slovo (15 = normální
# provoz/force; 4121 = interní override — měnič ignoruje force a trickle-nabíjí
# ~1,4 kW ze sítě; pozorováno v noci, ráno, poledne i večer, i mimo Time-Charging
# okno a i po jeho vynulování). 33116+ = fault registry.
BLOCK_STATE = (33095, 30)   # 33095..33124
STATE_WORD = (33095, "u16", 1.0)
FAULT_REGS = [33116, 33117, 33118, 33119, 33120, 33121]
