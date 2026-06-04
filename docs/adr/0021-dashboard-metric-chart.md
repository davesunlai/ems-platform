# 0021 – Volitelná metrika grafu na dashboardu (vč. SoC baterie)

## Stav
Přijato (v0.16.0)

## Kontext
Graf zařízení ukazoval napevno jen `pv_power`. Uživatel chtěl vidět i stav
nabití baterie (SoC) v grafu na stejných principech jako ostatní metriky.

## Rozhodnutí
- Dlaždice metrik na dashboardu jsou klikací → přepnou metriku grafu
  (stejný TimeChart, stejné okno/posun šipkami). Aktivní dlaždice zvýrazněna.
- Volba uživatele se drží (`picked` ref); 5s polling už metriku nepřepisuje
  zpět na výchozí, jen do první volby.
- Barva křivky dle metriky (`CHART_COLOR`): FVE zelená, baterie/SoC modrá,
  síť jantarová.
- SoC se nezarovnává nulami (zero-fill je jen pro `*_power`), takže mezera
  v datech křivku SoC neshodí na 0.

## Důsledky
- Bez serverové změny. Dashboard nově umí graf libovolné měřené veličiny.
