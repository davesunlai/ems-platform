# 0028 – Editace pravidel + hystereze nabíjení

## Stav
Přijato (v0.23.0)

## Kontext
Pravidla automatizace šla jen zapnout/vypnout/smazat, ne upravit. A nabíjení
při nízké ceně se mělo spouštět jen při hlubokém vybití a dojet do plna (bez
poskakování kolem prahu).

## Rozhodnutí
- Editace pravidel: tlačítko Upravit načte pravidlo do formuláře; uložení přes
  PUT (nahrazení params). Typ a ID se při editaci nemění.
- spot_charge dostal druhý práh `soc_start` (začni nabíjet jen pod ním) vedle
  `soc_max` (nabíjej až po něj). Hystereze přes skutečný režim měniče:
  start jen když SoC ≤ soc_start, pak nabíjí dál až po soc_max, teprve pak normál.
  Default soc_start=100 → staré rule beze změny chování.

## Důsledky
- Příklad „pod 50 % → do 100 %": soc_start=50, soc_max=100. Nepřebíjí se a neskáče.
- Vybíjení zatím beze změny; stejná hystereze se dá doplnit symetricky.
