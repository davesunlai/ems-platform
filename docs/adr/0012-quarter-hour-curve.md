# ADR 0012: Čtvrthodinová cenová křivka + historické okno (v0.8.0)

## Kontext
Od 10/2025 je denní trh OTE čtvrthodinový (15min); hodinové ceny jsou jen
průměr pro zpětnou kompatibilitu. Uživatel chce 15min rozlišení a okno zpět.

## Rozhodnutí
- Stahuje se čtvrthodinový endpoint (get-prices-json-qh) s fallbackem na
  hodinový (rozkopírovaný do 4 čtvrthodin), parsováno defenzivně.
- Sloty se ukládají s absolutním časem do `spot_history` (slot PK, price).
- Endpoint `/api/market/spot-curve?days=N` vrací sloty od (dnešek-(N-1)) do
  konce zítřka, agregované přes time_bucket na ~400 bodů (15min pro krátká
  okna, hrubší pro dlouhá).
- Frontend SpotCurve má tlačítka +/− pro okno: den → 30 dní zpět; časová osa,
  svislé hranice dnů, zvýrazněný aktuální slot, barvy dle prahů pravidel.

## Důsledky
- Historie se plní postupně (zpětně jen co se nasbírá), podobně jako u grafů.
- Připraveno na pozdější optimalizaci dle celé 15min křivky.
