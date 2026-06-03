# ADR 0001: Monitoring první, architektura control-ready

## Kontext
Cíl je monitoring i řízení napříč kritickou energetickou infrastrukturou.
Řízení reálných zařízení přidává tvrdé požadavky (latence, bezpečnost,
regulatorika, odpovědnost).

## Rozhodnutí
Stavíme architekturu *control-ready* (počítá s povelovou rovinou a edge
fail-safe), ale **nasazujeme nejdřív monitoring (read-only)**. Řízení se
zapíná per-modul až po validaci telemetrie na reálných datech.

## Důsledky
- První moduly nemají zápis do zařízení → nízké riziko.
- Povelová pipeline a edge autonomie se navrhují od začátku, neretrofitují.
