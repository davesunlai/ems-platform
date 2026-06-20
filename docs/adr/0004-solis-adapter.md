# ADR 0004 — Čtecí adaptér `solis` (Modbus TCP)

## Stav
Přijato (v0.31.0).

## Kontext
Nová (B2B) lokalita s měničem **Solis S6-EH3P50K-H** (3f HV hybrid, 50 kW,
2 battery packy). Stick na `192.168.6.180:502` jede čistý **Modbus TCP**
(port 8899 / Solarman zavřený). Potřebujeme telemetrii ve stejném
kanonickém modelu jako goodwe.

## Rozhodnutí
- Třetí čtecí adaptér `SolisAdapter` (vedle `goodwe`, `mock`), **read-only**.
- Transport Modbus TCP přes `pymodbus>=3.13` (`read_input_registers`,
  `count`/`device_id` keyword-only). Bloky U32/S32 skládány `(hi<<16)|lo`.
- Emituje STEJNÁ kanonická pole i znaménka jako goodwe:
  - `generation`: `pv_power` (33057-58), `energy_pv_total` (33029-30),
    `grid_power` (33130-31, **otočeno** — Solis má +export, EMS +import).
  - `storage`: `battery_soc`/`voltage`/`current` per pack (1: 33139/33133/33134,
    2: 34278/34289/34290) a `battery_power = U*I` (+nabíjení/−vybíjení).
- Dva packy řešeny parametrem `battery_pack` (1|2) → dva `storage` moduly.
- V UI Modbus jednotka pojmenovaná `device_id`; factory ji přemapuje na
  `unit`, aby nekolidovala s EMS `device_id` (id modulu).

## Mimo rozsah
Holding registry (0x03/0x06) pro ovládání — později samostatný zápisový
modul po získání oficiální RW mapy (NDA). `load_power` registr pro 3f
model zatím nepotvrzen (brief §9) → neemitujeme, doplníme po živém dočtení.
