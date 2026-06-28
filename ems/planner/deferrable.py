"""Časované spotřebiče (deferrable loads) — ekonomický merit-order soak (brief §4, §7).

JEDEN mechanismus, ne hardcoded „spirála". Každá zátěž má power_kw, value_per_kwh
(co je v ní kWh hodná) a constraints (strop kapacity / jistič). Dispatcher pustí
zátěž v hodině, kdy se její teplo/výnos vyplatí VÍC než marginální cena energie
(prodej v přebytku / nákup v deficitu), seřazeno od nejlevnější hodiny, do vyčerpání
kapacity (strop nádrže) a v rámci hlavičky jističe. Spirála = `n=1` případ:
value = hodnota_tepla[sezóna], strop = (T_max − I5)·kWh/°C.

Čistá funkce, bez DB. Vrací {hour: hold_bool} — hold=True když se topí z gridu
(deficit) → baterie má v té hodině DRŽET (nekrýt spotřebič ze self-consumption).
"""
from __future__ import annotations


def schedule_soak(pv_surplus_kw: list[float], p_imp: list[float], p_exp: list[float], *,
                  value_czk_kwh: float, power_kw: float, breaker_headroom_kw: list[float],
                  budget_kwh: float, daily_max_kwh: float | None = None) -> dict[int, bool]:
    """Naplánuj binární běh JEDNÉ zátěže (spirála MVP).

    - Hodina je eligibilní, když `value_czk_kwh ≥ marginální cena` (přebytek→prodej,
      deficit→nákup) a vejde se do jističe (`headroom ≥ power`).
    - Bere nejlevnější eligibilní hodiny, dokud nevyčerpá `budget_kwh` (strop nádrže)
      ani volitelný `daily_max_kwh`.
    - `hold=True` u hodin bez přebytku (topí se z gridu) → baterie HOLD.
    """
    n = len(pv_surplus_kw)
    e = float(power_kw)               # kWh za hodinu (binární, hodinové kroky)
    if e <= 0:
        return {}
    budget = float(budget_kwh)
    if daily_max_kwh is not None:
        budget = min(budget, float(daily_max_kwh))
    if budget < e * 0.5:
        return {}

    elig = []
    for h in range(n):
        surplus = (pv_surplus_kw[h] or 0.0) > 0.05
        marg = p_exp[h] if surplus else p_imp[h]        # co tě ta kWh teď stojí/vynese
        if value_czk_kwh >= marg and (breaker_headroom_kw[h] or 0.0) >= e - 1e-6:
            elig.append((marg, h, surplus))
    elig.sort(key=lambda x: x[0])                       # nejlevnější marginální cena první

    on: dict[int, bool] = {}
    for _marg, h, surplus in elig:
        if budget < e * 0.5:
            break
        on[h] = (not surplus)                           # HOLD baterie, když z gridu
        budget -= e
    return on


def heat_budget_kwh(tank_temp_c: float | None, tmax_c: float, kwh_per_deg: float,
                    fallback_kwh: float = 0.0) -> float:
    """Kolik tepla se ještě vejde: (T_max − aktuální I5)·kWh/°C. Bez čidla → fallback."""
    if tank_temp_c is None:
        return max(0.0, fallback_kwh)
    return max(0.0, (float(tmax_c) - float(tank_temp_c)) * float(kwh_per_deg))
