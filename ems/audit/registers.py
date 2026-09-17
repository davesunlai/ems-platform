"""Katalog registrů s významem podle manuálu (Solis RS485_MODBUS Hybrid, Appendix II) +
ověřené poznámky z pilotu. Klíč = adresa (raw, bez offsetu 30001)."""
SOLIS_INPUT = {
    33029: ("energy_pv_total", "u32", "kWh", "Celková vyrobená energie (kumulativní čítač měniče)"),
    33035: ("energy_today", "u16 ×0.1", "kWh", "Energie vyrobená dnes (čítač měniče, nuluje se o půlnoci)"),
    33057: ("pv_power", "u32", "W", "Celkový DC výkon FVE (součet všech stringů)"),
    33073: ("grid_voltage_l1", "u16 ×0.1", "V", "Síťové napětí fáze A"),
    33074: ("grid_voltage_l2", "u16 ×0.1", "V", "Síťové napětí fáze B"),
    33075: ("grid_voltage_l3", "u16 ×0.1", "V", "Síťové napětí fáze C"),
    33076: ("inverter_current_l1", "u16 ×0.1", "A", "Proud měniče fáze A"),
    33077: ("inverter_current_l2", "u16 ×0.1", "A", "Proud měniče fáze B"),
    33078: ("inverter_current_l3", "u16 ×0.1", "A", "Proud měniče fáze C"),
    33079: ("inverter_ac_power", "s32", "W", "Činný výkon měniče na AC straně (celkem)"),
    33093: ("temperature", "s16 ×0.1", "°C", "Teplota měniče"),
    33095: ("inverter_state", "u16", "", "Stav měniče: 3 = generuje, 15 = normální/force; 4121 = alarm IGFOL-F (1019)"),
    33116: ("inverter_fault", "u16 ×6", "", "Poruchová slova 1–6 (bitová pole alarmů)"),
    33130: ("grid_power", "s32", "W", "Činný výkon elektroměru na předávacím místě. Solis: + = DO sítě (export), − = ZE sítě (import). "
                                     "EMS znaménko otáčí (+ = odběr)."),
    33133: ("battery_voltage_1", "u16 ×0.1", "V", "Napětí baterie 1 (strana měniče)"),
    33134: ("battery_current_1", "s16 ×0.1", "A", "Proud baterie 1 — na tomto modelu MAGNITUDA (vždy +), směr z 33135"),
    33135: ("battery_direction_1", "u16", "", "Směr baterie 1: 0 = nabíjení, 1 = vybíjení"),
    33139: ("battery_soc_1", "u16", "%", "Stav nabití baterie 1"),
    33140: ("battery_soh_1", "u16", "%", "Zdraví baterie 1"),
    33144: ("battery_temp_1", "s16 ×0.1", "°C", "Teplota baterie 1"),
    33147: ("house_load", "u16", "W", "Zátěž domu podle měniče (backup/household load)"),
    33149: ("battery_power_inv", "s32", "W", "Výkon baterie podle měniče (manuál: + nabíjení / − vybíjení) — křížová kontrola "
                                             "k EMS výpočtu z V×I packů (metrika battery_power_inv)"),
    34278: ("battery_soc_2", "u16", "%", "Stav nabití baterie 2"),
    34279: ("battery_soh_2", "u16", "%", "Zdraví baterie 2"),
    34282: ("battery_temp_2", "s16 ×0.1", "°C", "Teplota baterie 2 (34281 vracelo nesmysl)"),
    34289: ("battery_voltage_2", "u16 ×0.1", "V", "Napětí baterie 2"),
    34290: ("battery_current_2", "s16 ×0.1", "A", "Proud baterie 2 — MAGNITUDA (ověřeno 3. 9. 2026), směr z 34291"),
    34291: ("battery_direction_2", "u16", "", "Směr baterie 2: 0 = nabíjení, 1 = vybíjení (ověřeno živě)"),
}
SOLIS_HOLDING = {
    43110: ("work_mode", "bitfield", "", "Pracovní režim (0x21 = Self-Use + grid-charge bit)"),
    43135: ("force", "u16", "", "Nucený režim: 0 = vypnuto, 1 = nabíjení, 2 = vybíjení"),
    43136: ("force_charge_power", "u16", "×10 W", "Výkon nuceného nabíjení (kW × 100)"),
    43129: ("force_discharge_power", "u16", "×10 W", "Výkon nuceného vybíjení (kW × 100)"),
    43024: ("backup_soc", "u16", "%", "Záložní SoC (pod něj se nevybíjí)"),
    43141: ("charge_current_limit", "u16 ×0.1", "A", "Limit nabíjecího proudu"),
    43142: ("discharge_current_limit", "u16 ×0.1", "A", "Limit vybíjecího proudu"),
}
# metrika EMS → registr(y) + jak se z nich hodnota skládá
METRIC_SOURCE = {
    "pv_power": ("33057–33058", "u32 → W"),
    "energy_today": ("33035", "u16 × 0.1 → kWh"),
    "energy_pv_total": ("33029–33030", "u32 → kWh"),
    "grid_power": ("33130–33131", "s32 → W; EMS = −(registr) (otočení znaménka: + odběr)"),
    "battery_soc": ("33139, 34278", "průměr SoC packů 1 a 2"),
    "battery_soc_1": ("33139", "u16 → %"), "battery_soc_2": ("34278", "u16 → %"),
    "battery_voltage_1": ("33133", "u16 × 0.1 → V"), "battery_voltage_2": ("34289", "u16 × 0.1 → V"),
    "battery_current_1": ("33134", "s16 × 0.1 → A (magnituda)"), "battery_current_2": ("34290", "s16 × 0.1 → A (magnituda)"),
    "battery_power_1": ("33133 × 33134, směr 33135", "V × A × (−1 při vybíjení) → W"),
    "battery_power_2": ("34289 × 34290, směr 34291", "V × A × (−1 při vybíjení) → W"),
    "battery_power": ("packy 1+2", "battery_power_1 + battery_power_2 (+ nabíjení / − vybíjení)"),
    "inverter_state": ("33095", "u16"),
    "temperature": ("33093", "s16 × 0.1 → °C"),
    "house_load_inv": ("33147", "u16 → W (zátěž domu podle měniče)"),
    "battery_power_inv": ("33149–33150", "s32 → W (výkon baterie podle měniče)"),
    "inverter_ac_power": ("33079–33080", "s32 → W (AC výkon měniče)"),
    "inverter_current_l1": ("33076", "u16 × 0.1 → A"), "inverter_current_l2": ("33077", "u16 × 0.1 → A"), "inverter_current_l3": ("33078", "u16 × 0.1 → A"),
    "grid_voltage_l1": ("33073", "u16 × 0.1 → V"), "grid_voltage_l2": ("33074", "u16 × 0.1 → V"), "grid_voltage_l3": ("33075", "u16 × 0.1 → V"),
}


def describe(addr: int) -> str:
    r = SOLIS_INPUT.get(addr) or SOLIS_HOLDING.get(addr)
    return f"{addr}: {r[0]} [{r[1]}] {r[2]} — {r[3]}" if r else f"{addr}: (bez popisu)"
