# ADR 0018: Spínání suchého kontaktu měniče dle SOC (v0.13.0)

## Kontext
Sepnout kontakt (relé) na střídači po nabití na horní mez SOC, rozepnout při
poklesu na dolní mez — hystereze (např. sepnout na 100 %, rozepnout na 95 %).

## Rozhodnutí
- Goodwe ET: ovládání přes setting `load_control_switch` (47596, 1/0).
  set_load_switch/read_load_switch v goodwe_control (write_setting + read-back).
- Modul ems/contact: tabulka contact_config (device_id, enabled, upper_soc,
  lower_soc, contact_on, last_decision). Hystereze v engine.evaluate_contacts():
  SOC ≥ upper → sepnout, SOC ≤ lower → rozepnout; stav drží DB (edge-trigger,
  bez poskakování). Volá se v kolektorovém tiku. Audit jako contact:auto.
- Endpointy /api/contact (GET read; PUT control; POST {id}/switch ruční test).
- Stránka „Kontakt" (control): horní/dolní mez, zapnutí, stav, ruční test.

## Důsledky
- Měnič musí mít Load Control v režimu respektujícím SW přepnutí — ověřit ručním
  tlačítkem (load_control_mode se zatím nenastavuje automaticky).
