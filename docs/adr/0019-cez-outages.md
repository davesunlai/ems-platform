# 0019 – Plánované odstávky distribuce (ČEZ)

## Stav
Přijato (v0.14.0)

## Kontext
Potřebujeme u lokalit zobrazovat plánované odstávky elektřiny od distributora,
aby šlo dopředu upravit provoz (nabití baterie před odstávkou apod.).

## Rozhodnutí
- Univerzální `OutageProvider` (ABC) + `CezOutageProvider`. Pozdější EGD/PRE = další provider.
- Zdroj ČEZ: anonymní endpoint distribučního portálu (DIP), bez přihlášení —
  GET token (`X-Request-Token`) + POST `vyhledani-odstavek`. Payload dle priority
  **EAN → číslo elektroměru → adresa (PSČ, město, ulice)**.
- U lokality se v adminu zadají identifikátory; dotaz použije první vyplněný.
- Odstávky se publikují min. 15 dní předem → kolektor stahuje 1× denně
  (`refresh_all`, prune > 3 dny po skončení). Tabulka `planned_outages` (uid PK).
- Zobrazení v adminu lokality (sekce „Plánované odstávky") + ruční „Načíst teď".

## Důsledky
- Nová závislost `httpx`. ČEZ endpoint je neoficiální → ošetřeno výjimkami,
  případný výpadek formátu neshodí kolektor.
