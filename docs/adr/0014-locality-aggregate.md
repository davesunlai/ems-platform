# ADR 0014: Souhrnný graf lokality (v0.10.0)

## Kontext
Při více střídačích na lokalitě chce uživatel vidět součet výroby FVE a k tomu
spotřebu lokality (a u jednoho střídače i odběr ze sítě).

## Rozhodnutí
- Dashboard se seskupuje podle lokality (z `/api/devices`, pole locality).
- Pro každou skupinu „Souhrn lokality": víceřadý graf — výroba FVE (součet
  pv_power přes střídače), spotřeba (load_power), síť (grid_power, +import/−export).
  Zobrazí se jen řady, které mají data (pokud to střídač měří).
- Backend: `/api/devices/aggregate?ids=&metrics=&minutes=` — per-bucket součet
  průměrů zařízení (time_bucket), ~400 bodů; okno 6 h–30 dní (+/− jako u grafů).
- Funguje pro 1 i N střídačů; zařízení bez lokality jsou ve skupině „Bez lokality".

## Důsledky
- Energetický přehled na úrovni místa; základ pro pozdější bilance a optimalizaci.
