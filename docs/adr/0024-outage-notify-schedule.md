# 0024 – Čas a opakování oznámení odstávek

## Stav
Přijato (v0.19.0)

## Kontext
Oznámení odstávek běželo „těsně po půlnoci UTC" (cca 02:00 lokálně) a jen jednou.
Chtěli jsme nastavitelnou hodinu a opakovaná připomenutí až do odstávky.

## Rozhodnutí
- `.env`: `EMS_OUTAGE_HOUR` (hodina denního běhu, pražský čas, default 7) a
  `EMS_OUTAGE_REMIND_DAYS` (interval připomínek ve dnech, default 2; 0 = jen úvodní).
- Kolektor spustí denní `refresh_all` při prvním tiku, kdy je pražská hodina >= HOUR
  a den se liší od posledního běhu.
- Notifikace řízená sloupcem `planned_outages.last_notified` (DATE), ne diffem:
  pošle se, když je NULL (úvodní) nebo když uplynulo >= REMIND_DAYS dní; pak se
  `last_notified` nastaví na dnešek. Odolné vůči restartům i ručnímu „Načíst teď".
- Kolektor dostal do compose SMTP + EMS_BASE_URL (dřív chyběly → denní maily
  z kolektoru tiše selhávaly); api dostalo REMIND_DAYS pro ruční notifikaci.

## Důsledky
- Připomínky chodí každých N dní až do termínu. Při N=2 a publikaci 15 dní předem
  to může být ~7 e-mailů na odstávku – laditelné přes .env (vyšší N nebo 0).
