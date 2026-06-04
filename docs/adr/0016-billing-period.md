# ADR 0016: Zúčtovací období lokality + přetoky (v0.12.0)

## Kontext
Uživatel (ČEZ) má zúčtovací období s limitem přetoků (např. 3,5 MWh). Chce
souhrn po měsících od začátku období, součet za období a hlídání přetoků.

## Rozhodnutí
- Lokalita rozšířena o: billing_start (datum), billing_months (default 12),
  export_limit_kwh, alert_enabled, autolimit_enabled, alert_email
  (+ alert_fired/limit_applied/period_anchor pro budoucí hlídač).
- Období: current_period(start, months, today) → [start, end), po konci od nuly.
- Energie: měsíční bilance z výkonových vzorků, integrace po hodinových koších
  (avg výkon × 1 h). Přetoky/odběr z čistého výkonu sítě: export=max(0,−net),
  import=max(0,net). Endpoint GET /api/localities/{id}/billing (read).
- /api/devices vrací locality_id; dashboard u skupiny lokality ukáže tabulku
  „Zúčtovací období" (měsíce: výroba/spotřeba/přetoky/odběr + součet) a pruh
  přetoky vs. limit. Admin stránka „Zúčtování" pro nastavení.

## Důsledky
- Energie je aproximace integrací po hodinách (dost přesné na MWh bilanci).
- v0.13.0: e-mail při překročení limitu (edge-trigger) + auto-omezení přetoků
  na 0 přes goodwe set_grid_export_limit (po ověření chování měniče).


## v0.12.1
- Oprava znaménka sítě: kladný grid_power = dodávka (export), záporný = odběr
  (import) — dle reálných dat z ČEZ. Upraven i popisek živého grafu sítě.
- Baseline per lokalita: ruční dodávka/odběr (kWh) od začátku období do spuštění
  měření; přičítá se k součtu za období, váže se na začátek období (po přechodu
  na další období se neuplatní). Řádek „Před spuštěním měření" v tabulce.
