"""Amplitudy na EFEKTIVNÍ ceně (ne na syrovém spotu) + plánování 6 kW spirály jako
binárního odložitelného spotřebiče. Čisté funkce — vstupem jsou už hotové řady
efektivní ceny (z pricing.cost.price_czk_kwh) a predikce; bez I/O, snadno testovatelné.

Konvence:
- `ts_list`  : seznam datetime (hodinové sloty, vzestupně).
- `p_imp`/`p_exp` : efektivní import/export cena per slot (CZK/kWh) — stejná, jakou staví planner.
- valley = nejlevnější souvislá okna na import ceně (nabíjení/topení),
  peak  = nejdražší souvislá okna na export ceně (vybíjení do sítě).

Brief: SMART-CONTROL §4 (amplitudy) a §5 (spirála). Distribuce je flat (VT/NT split neřešíme),
takže amplitudy jedou na efektivní ceně dle režimu (SPOT = spot + přirážky; VT/NT = obchodní dvoutarif).
"""
from __future__ import annotations

from datetime import datetime, timedelta


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    i = int(round((len(sorted_vals) - 1) * pct / 100.0))
    return sorted_vals[max(0, min(len(sorted_vals) - 1, i))]


def find_windows(ts_list, prices, *, valley: bool, max_windows: int = 4,
                 threshold_pct: float = 33.0, min_hours: int = 1) -> list[dict]:
    """Souvislá okna, kde je cena pod (valley) / nad (peak) prahem percentilu.

    Okna se seřadí podle průměrné ceny (valley = od nejlevnějšího, peak = od nejdražšího)
    a vrátí se nejlepších `max_windows`. Práh = `threshold_pct`-ní percentil (valley dole,
    peak nahoře).
    """
    pts = [(t, float(p)) for t, p in zip(ts_list, prices) if p is not None]
    if len(pts) < 1:
        return []
    vals = sorted(p for _, p in pts)
    thr = _percentile(vals, threshold_pct if valley else (100.0 - threshold_pct))

    runs: list[list] = []
    cur: list = []
    for t, p in pts:
        hit = (p <= thr) if valley else (p >= thr)
        if hit:
            if cur and (t - cur[-1][0]).total_seconds() <= 3700:   # souvislé hodiny (tolerance na DST)
                cur.append((t, p))
            else:
                if cur:
                    runs.append(cur)
                cur = [(t, p)]
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)

    wins = []
    for r in runs:
        if len(r) < min_hours:
            continue
        ps = [p for _, p in r]
        wins.append({
            "from": r[0][0], "to": r[-1][0] + timedelta(hours=1), "hours": len(r),
            "avg": round(sum(ps) / len(ps), 4), "min": round(min(ps), 4), "max": round(max(ps), 4),
        })
    wins.sort(key=lambda w: w["avg"], reverse=not valley)
    return wins[:max_windows]


def find_amplitudes(ts_list, p_imp, p_exp, **opts) -> dict:
    """{'valley': [...okna nejlevnějšího importu...], 'peak': [...nejdražšího exportu...]}"""
    return {
        "valley": find_windows(ts_list, p_imp, valley=True, **opts),
        "peak": find_windows(ts_list, p_exp, valley=False, **opts),
    }


def schedule_spiral_binary(ts_list, p_imp, pv_surplus_kw, *, energy_target_kwh: float,
                           max_power_kw: float = 6.0, deadline: datetime | None = None,
                           breaker_headroom_kw=None, now: datetime | None = None,
                           pv_on_frac: float = 0.5) -> dict:
    """6 kW spirála jako BINÁRNÍ deferrable load (resistivní coil — jen ON/OFF).

    Pořadí zdrojů (SMART-CONTROL §5): 1) PV přebytek → 2) nejlevnější valley import.
    Každá zapnutá hodina = `min(max_power_kw, headroom)` kWh; respektuje strop jističe
    (`breaker_headroom_kw[h]`). Plní do `energy_target_kwh` před `deadline`.

    Vrací {'slots': [{from,to,kw,source,price}], 'energy_kwh', 'target_kwh', 'shortfall_kwh'}.
    """
    n = len(ts_list)
    if breaker_headroom_kw is None:
        breaker_headroom_kw = [max_power_kw] * n
    now = now or (ts_list[0] if ts_list else None)
    chosen: dict[int, dict] = {}
    energy = 0.0

    def power_at(i: int) -> float:
        return max(0.0, min(max_power_kw, float(breaker_headroom_kw[i])))

    def before_deadline(t: datetime) -> bool:
        return deadline is None or t < deadline

    # 1) PV přebytek — opportunisticky topit, když je čím (převážně ze slunce)
    for i, t in enumerate(ts_list):
        if now is not None and t < now:
            continue
        if not before_deadline(t):
            continue
        if energy >= energy_target_kwh:
            break
        surplus = float(pv_surplus_kw[i] or 0)
        pw = power_at(i)
        if surplus >= pv_on_frac * max_power_kw and pw > 0:
            kwh = pw  # 1h slot
            chosen[i] = {"from": t, "to": t + timedelta(hours=1), "kw": round(pw, 2),
                         "source": "pv", "price": (round(p_imp[i], 4) if i < len(p_imp) else None)}
            energy += kwh

    # 2) zbytek do cíle → nejlevnější valley hodiny před deadline (pod jistič)
    if energy < energy_target_kwh:
        cands = []
        for i, t in enumerate(ts_list):
            if i in chosen or (now is not None and t < now) or not before_deadline(t):
                continue
            if power_at(i) <= 0:
                continue
            cands.append((float(p_imp[i]) if i < len(p_imp) else 0.0, i, t))
        cands.sort(key=lambda x: x[0])
        for price, i, t in cands:
            if energy >= energy_target_kwh:
                break
            pw = power_at(i)
            chosen[i] = {"from": t, "to": t + timedelta(hours=1), "kw": round(pw, 2),
                         "source": "valley", "price": round(price, 4)}
            energy += pw

    slots = [chosen[i] for i in sorted(chosen)]
    return {
        "slots": slots,
        "energy_kwh": round(energy, 2),
        "target_kwh": round(energy_target_kwh, 2),
        "shortfall_kwh": round(max(0.0, energy_target_kwh - energy), 2),
    }


def energy_from_temp(tank_liters: float, delta_t_c: float, eff: float = 1.0) -> float:
    """Energie na ohřev nádrže o ΔT: E[kWh] = m·c·ΔT / 3600 / eff. Voda c=4.186 kJ/(kg·K)."""
    if tank_liters <= 0 or delta_t_c <= 0:
        return 0.0
    kj = tank_liters * 4.186 * delta_t_c           # kg ≈ litry
    return kj / 3600.0 / max(0.05, eff)
