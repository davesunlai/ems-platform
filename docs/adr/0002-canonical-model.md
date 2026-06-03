# ADR 0002: Kanonický datový model

## Kontext
Univerzalita napříč různými zdroji (FVE, BESS, nabíječka, síť) vyžaduje
společný jazyk, jinak vznikne sbírka nekompatibilních integrací.

## Rozhodnutí
Jádro pracuje výhradně s kanonickým modelem (Reading/Sample/Metric).
Adaptéry překládají nativní data do modelu. Znaménkové konvence jsou
fixní (viz ems/core/model.py).

## Důsledky
- Úložiště, API i web jsou nezávislé na konkrétním protokolu.
- Sémantiku lze později mapovat na IEC CIM bez přepisu jádra.
