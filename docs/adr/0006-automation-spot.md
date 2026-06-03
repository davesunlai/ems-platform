# ADR 0006: Automatizace dle spotové ceny (Fáze D)

## Kontext
Spojení řízení (C) s trhem: automaticky nabíjet baterii při nízké spotové ceně.

## Rozhodnutí
- Zdroj cen: veřejné API OTE (spotovaelektrina.cz), cache v `market_state`.
  Ruční override (`manual`) pro testování bez čekání na trh.
- Pravidla v `automation_rules` (typ `spot_charge`): target_module,
  price_threshold, soc_max, charge_power.
- Engine běží v kolektoru, vyhodnocuje každý cyklus.
- **Bezpečnost:** povel se pošle jen když SKUTEČNÝ režim měniče (z device_state)
  neodpovídá záměru → samoopravné, žádné spamování; min. interval mezi povely;
  každý automatický povel do auditu jako `automation:<rule>`; pravidla vypínatelná.

## Důsledky
- První reálné VPP chování: cena trhu → fyzická akce na baterii.
- Rozšiřitelné na další typy pravidel (discharge při vysoké ceně, FCR, …).
- Pozn.: rozhodování dle aktuální ceny; plánování dle celé denní křivky a
  optimalizace napříč trhy je další krok.
