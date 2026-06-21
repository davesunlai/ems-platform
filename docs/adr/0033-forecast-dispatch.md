# 0033 — Predikce výroby z počasí (čtecí základ)

## Status
Přijato — první commit (čtecí část). Dispatch/řízení samostatně později.

## Kontext
Potřebujeme predikci výroby FVE (24–48 h) pro nový graf a (později) prediktivní
řízení baterie/akumulace/EV podle spotu. Závazný podklad: `FORECAST-DISPATCH-BRIEF.md`.
Pořadí dle §14: nejdřív čtecí část (zdroj počasí + cache + PV model + samokalibrace
PR), teprve pak druhý zdroj, load_forecast, graf a až nakonec planner/řízení.

## Rozhodnutí (tento commit)
Modul `ems/forecast/` — tři role oddělené (provideři / model / služba):
- **providers.py** — `WeatherProvider` (base) + `OpenMeteoProvider`. Open-Meteo
  `global_tilted_irradiance` (rovina panelu), `temperature_2m`, `cloud_cover`.
  Azimut **0=jih, −90=východ, +90=západ** (ověřeno v dokumentaci). Geokódování
  města (fulltext → lat/lon) přes Open-Meteo geocoding (zdarma, bez klíče).
- **model.py** — `P_ac = kWp × GTI/1000 × PR × temp_factor`, NOCT teplota článku,
  bifaciální zisk (placeholder +10 %). Per blok, sečteno. `MODEL_VERSION="om-pv-1"`.
- **calibrate.py** — PR se sám dolaďuje proti reálné výrobě (`energy_today` z měniče),
  vyhlazeně, ořez 0.30–0.98.
- **db.py** — cache `weather_forecast`, `pv_forecast` + konfigurace `pv_block`.
- **service.py** — fetch per blok → model → sečíst → cache (`open_meteo`+`avg`) → kalibrace.
- **routes.py** — `GET /api/forecast/{id}`, `POST /{id}/refresh`, `GET/PUT /{id}/blocks`,
  `GET /api/forecast/geocode`.

Konfigurace na lokalitě: `lat`, `lon`, `pv_kwp_total`; bloky v `pv_block`
(typ normal/bifacial, podíl %, směr, sklon, PR). Kolektor přepočítává à 3 h
(`tick_forecast`), čtecí — žádné zápisy do měniče.

## Mimo rozsah (další commity dle §14)
Forecast.Solar + průměrování + pásmo nejistoty; `load_forecast`; graf 24–48 h;
`planner.py` (greedy) + `dispatch_schedule` + napojení na `control_queue`;
`deferrable_load`; rolling-horizon + outages. Versionovaný `locality_tariff`
(§6.1) nahradí plochá cenová pole z v0.31.19 — přijde s cenami/dispatchem.

## Důsledky
Čtecí část stojí samostatně a nic neovládá. Greedy MVP potvrzen (LP případně později).
Před zapnutím řízení doplnit cenové parametry (CZK/MWh), kurz EUR→CZK, dvoutarif,
outage_reserve a ověřit scale Solis registru 43136.
