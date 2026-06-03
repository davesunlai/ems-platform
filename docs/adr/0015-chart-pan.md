# ADR 0015: Posun časové osy táhnutím + datum rozsahu (v0.11.0)

## Kontext
Uživatel chtěl posouvat časovou osu grafů táhnutím (pan) a vidět čitelně datum.

## Rozhodnutí
- Backend: history() i aggregate_history() mají parametr `offset` (minuty zpět);
  okno = [now-(minutes+offset), now-offset]. Endpointy device_history a
  devices_aggregate berou `offset` (clamp 0..525600, ~rok).
- Frontend: posun šipkami ◀ ▶ o jeden aktuálně nastavený úsek (délku okna);
  krok = WIN[win].min, ◀ zpět (offset += okno), ▶ vpřed (offset −= okno, min 0).
  (Pův. záměr táhnutí myší v0.11.0 byl ve v0.11.1 nahrazen šipkami — pohodlnější.)
- Nad grafem popisek rozsahu (rangeLabel) s datem a časem; tlačítko „→ teď"
  vrátí offset na 0. Při offsetu>0 se vypne auto-refresh, ať historický pohled
  neposkakuje. Změna délky okna (+/−) resetuje offset.

## Důsledky
- Procházení historie bez nutnosti měnit délku okna; jasné datum rozsahu.
- Pan zatím u power grafů (zařízení + souhrn lokality); spotová křivka beze změny.
