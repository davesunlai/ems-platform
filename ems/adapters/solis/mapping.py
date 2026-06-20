"""Mapa čtecích registrů Solis S6-EH3P50K-H (input, FC 0x04).

Adresy jsou "raw" (bez offsetu 30001) a jsou OVĚŘENÉ na reálném kuse —
viz SOLIS-ADAPTER-BRIEF.md §9 (telemetrie) a §10 (dva battery packy).

Každá položka = (adresa, typ, měřítko). Typy: "u16" | "s16" | "u32" | "s32".
U32/S32 se čtou jako count=2 a skládají (hi<<16)|lo.
"""
from __future__ import annotations

# --- Systémové registry (společné pro celý měnič) ---
REG_PV_POWER = (33057, "u32", 1.0)        # W  — celkový DC výkon FVE
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

# --- Baterie: dva packy, KAŽDÝ MÁ JINÝ LAYOUT (ne offset!) viz brief §10 ---
# voltage = napětí inv-side (0.1 V), current = proud (0.1 A, + nabíjení / − vybíjení)
BATTERY_PACKS = {
    1: {
        "soc": (33139, "u16", 1.0),
        "voltage": (33133, "u16", 0.1),
        "current": (33134, "s16", 0.1),
        "soh": (33140, "u16", 1.0),
        "temp": (33144, "s16", 0.1),
    },
    2: {
        "soc": (34278, "u16", 1.0),
        "voltage": (34289, "u16", 0.1),
        "current": (34290, "s16", 0.1),   # kandidát dle briefu §10 — ověřit živě
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
BLOCK_BAT1 = (33133, 18)   # 33133..33150: baterie 1
BLOCK_BAT2 = (34275, 16)   # 34275..34290: baterie 2
