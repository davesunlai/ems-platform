# ADR 0010: Cenová křivka + okamžitý živý feed (v0.7.1)

## Rozhodnutí
- Kolektor stahuje i hodinovou křivku (dnes+zítra) z OTE API a ukládá do
  market_state.curve; stahuje se vždy (i během ručního testu ceny).
- "Zpět na živý feed" (clear manual) teď okamžitě stáhne aktuální cenu i křivku
  — nečeká se na refresh cyklus (dřív až 5 min).
- Frontend: SVG křivka na stránce Automatizace s barevným vyznačením, kde by
  pravidla nabíjela (zeleně) / vybíjela do sítě (červeně) podle prahů, +
  prahové čáry a zvýraznění aktuální hodiny. Předpověď dle ceny (bez budoucího SoC).

## Důsledky
- Vizuální základ pro pozdější optimalizaci dle celé denní křivky.
