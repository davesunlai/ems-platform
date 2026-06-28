"""Noční rezerva a adaptivní ranní SOC (brief §1, §2). Čisté funkce, bez DB.

Princip jednoho denního cyklu:
  ráno min SOC → přes den dobije FVE → večer/noc kryje dům+TČ → ráno zase min SOC.
Noční rezerva = kolik kWh musí být v baterii při západu, aby pokryla dům+TČ přes
noc do ranního naběhnutí FVE (§2). Ranní cíl SOC je adaptivní podle ZÍTŘEJŠÍ FVE:
jasno → nízko (slunce dobije), zataženo → drž víc (§1). Vše proti DOLNÍ hraně FVE.
"""
from __future__ import annotations


def night_indices(pv_low_kw: list[float], thresh_kw: float = 0.3) -> tuple[int, int]:
    """Najde NEJBLIŽŠÍ noční okno (souvislý blok nízké FVE) → (start, end_exkluzivně).

    Přeskočí aktuální denní světlo, pak sebere souvislý blok kde pv_low < práh.
    Když je noc už teď (pv_low[0] < práh), start=0. Bez noci v horizontu → (n, n).
    """
    n = len(pv_low_kw)
    i = 0
    while i < n and (pv_low_kw[i] or 0.0) >= thresh_kw:   # přeskoč denní světlo
        i += 1
    start = i
    while i < n and (pv_low_kw[i] or 0.0) < thresh_kw:    # sber noc
        i += 1
    return start, i


def night_reserve_kwh(load_kw: list[float], hp_kw: list[float], pv_low_kw: list[float],
                      night_start: int, night_end: int, outage_kwh: float = 0.0) -> float:
    """Σ (dům + TČ − FVE_dolní)⁺ přes noční okno + výpadková rezerva (§2)."""
    total = 0.0
    for i in range(night_start, night_end):
        deficit = (load_kw[i] or 0.0) + (hp_kw[i] or 0.0) - (pv_low_kw[i] or 0.0)
        if deficit > 0:
            total += deficit                  # hodinové kroky → kWh
    return total + max(0.0, outage_kwh)


def tomorrow_surplus_kwh(pv_low_kw: list[float], load_kw: list[float], hp_kw: list[float],
                         day_start: int, hours: int = 14) -> float:
    """Σ (FVE_dolní − dům − TČ)⁺ přes zítřejší den (po skončení nejbližší noci).
    Konzervativně z DOLNÍ hrany FVE — kolik baterii reálně dobije."""
    total = 0.0
    for i in range(day_start, min(day_start + hours, len(pv_low_kw))):
        s = (pv_low_kw[i] or 0.0) - (load_kw[i] or 0.0) - (hp_kw[i] or 0.0)
        if s > 0:
            total += s
    return total


def adaptive_morning_soc_kwh(tomorrow_surplus: float, *, soc_min_kwh: float, cap_kwh: float,
                             night_reserve_kwh: float) -> float:
    """Ranní cíl SOC (kWh): jasno zítra → soc_min (sjede nízko), zataženo → drž víc (§1).

    need = kolik FVE musí zítra dodat, aby z soc_min dobila plnou. Když zítřejší
    (dolní) přebytek pokryje need → klidně sjeď na soc_min. Když ne → nech v baterii
    chybějící díl (až do noční rezervy), ať zataženého rána není málo.
    """
    need = max(0.0, cap_kwh - soc_min_kwh)
    if tomorrow_surplus >= need:
        return soc_min_kwh
    deficit = need - tomorrow_surplus
    extra = min(deficit, max(0.0, night_reserve_kwh - soc_min_kwh))
    return max(soc_min_kwh, min(soc_min_kwh + extra, night_reserve_kwh))


def floor_profile_kwh(n: int, night_start: int, night_end: int, *, soc_min_kwh: float,
                      night_reserve_kwh: float, morning_soc_kwh: float) -> list[float]:
    """Per-hodinová spodní mez SOC (kWh):
      - před nocí: night_reserve  (energii na noc neprodávej/neutrácej ve špičce)
      - během noci: morning_soc    (kryj dům+TČ, sjeď až na ranní cíl)
      - po noci:   soc_min         (FVE zase dobije)
    """
    out = []
    for h in range(n):
        if h < night_start:
            out.append(max(soc_min_kwh, night_reserve_kwh))
        elif h < night_end:
            out.append(morning_soc_kwh)
        else:
            out.append(soc_min_kwh)
    return out
