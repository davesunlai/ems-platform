# ADR 0011: Osy grafů a posuvné časové okno (v0.7.2)

## Rozhodnutí
- Dashboardový graf výkonu má osy: X = čas (popisky HH:MM, u delších oken datum),
  Y = hodnota s jednotkou (W se zobrazuje jako kW). Nová komponenta TimeChart.
- Tlačítka +/− mění zpětné okno v krocích 6 h → 12 h → 24 h → 3 d → 7 d → 14 d → 30 d.
  „−" zkracuje (min 6 h), „+" prodlužuje (max 30 dní).
- Backend: history agreguje přes time_bucket na ~400 bodů bez ohledu na délku okna
  (měsíc dat = stovky bodů, ne 260k). Endpoint omezuje okno na 6 h–30 dní.
- Historie se načítá odděleně od telemetrie (latest po 5 s, historie po 60 s
  a při změně okna), ať dlouhá okna nezatěžují DB každých 5 s.
- Spotová křivka má popisky os: X = hodiny (po 6 h, + dnes/zítra), Y = Kč/MWh.

## Důsledky
- Vizuální základ pro pozdější přiblížení/výběr rozsahu a delší retenci dat.
