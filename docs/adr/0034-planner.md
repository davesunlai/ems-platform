# 0034 — Prediktivní plánovač (greedy MVP)

## Status
Přijato — krok 6. Plán se počítá vždy (poradně); řízení je opt-in.

## Rozhodnutí
`ems/planner/` — čistá funkce `core.plan()` (greedy): self-use (priorita FVE),
nabíjení v nejlevnějším spotovém okně (s pojistkou „nech místo pro očekávanou FVE"),
volitelně vybíjení do sítě ve špičce; vždy nad floor = soc_min + outage_reserve.
Cena z versionovaného tarifu (VT/NT). Vstup: predikce výroby/zátěže + spot.
Výstup `dispatch_schedule` (akce, SoC trajektorie, toky, důvod).

Konfigurace per lokalita (`planner_config`): `enabled` (řídí měnič), 
`allow_grid_discharge` (43136 neověřen → default NE), kapacita, soc_min, 
outage_reserve, max nabíjení/vybíjení, horizont.

Řízení: kolektor `tick_planner` přepočítává à 30 min a u zapnutých lokalit 
enqueuuje aktuální akci PŘI ZMĚNĚ (force BEZ syrového výkonu → jede na nastavených 
limitech proudu, obejde 43136), source='planner'. 

Precedence: zapnutý plánovač přebírá řízení — reaktivní spot pravidla jeho modulů 
se v `evaluate_all` přeskočí; Automatizace to ukazuje badgem „⚠ přebírá plánovač".

Vizualizace: SoC trajektorie v grafu predikce na dashboardu.

## Mimo rozsah (dále)
LP optimum; deferrable_load (spirála) + EV; rolling-horizon + výpadky; 
vážení zdrojů predikce dle přesnosti; ověření scale 43136 pro grid-discharge výkon.
