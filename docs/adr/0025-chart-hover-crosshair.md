# 0025 – Hover svislá čára a hodnoty v grafech

## Stav
Přijato (v0.20.0)

## Kontext
Grafy neměly odečet hodnot. Uživatel chce při přejezdu myší svislou čáru
u kurzoru a hodnoty na dané pozici.

## Rozhodnutí
- TimeChart i MultiChart: onMouseMove nad grafem přepočte X z viewBoxu,
  najde nejbližší bod(y) v čase a vykreslí svislou přerušovanou čáru + zvýrazněný
  bod a bublinu s časem a hodnotou. MultiChart ukáže hodnoty všech řad naráz.
- Bublina je polohovaná v % šířky (mapuje viewBox na 100% šířku SVG),
  pointer-events: none, aby nerušila.
- Bez externí knihovny a bez serverové změny.

## Důsledky
- Drobně více práce v renderu při pohybu myší (lineární hledání nejbližšího bodu),
  pro typické okno zanedbatelné.
