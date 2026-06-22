"""Greedy MVP plánovač (čistá funkce, testovatelná bez DB).

Vstup: hodinové řady výroby/zátěže (kWh), cen nákup/prodej (CZK/kWh), kapacita
a stav baterie, limity. Výstup: hodinový plán s SoC trajektorií, akcí, tokem
baterie a důvodem. Bilance preferuje vlastní spotřebu; navíc nabíjí v nejlevnějším
okně a (volitelně) vybíjí do sítě ve špičce — vždy s rezervou (floor).

Není to optimum (LP přijde později), ale je to srozumitelné a vysvětlitelné.
"""
from __future__ import annotations


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def plan(ts, pv, load, p_imp, p_exp, *, cap_kwh, soc_now_pct, floor_pct,
         max_charge_kwh, max_discharge_kwh, allow_grid_discharge=False) -> list[dict]:
    n = len(ts)
    soc = soc_now_pct / 100.0 * cap_kwh
    floor = floor_pct / 100.0 * cap_kwh

    # nejlevnější / nejdražší hodiny horizontu pro arbitráž
    order_imp = sorted(range(n), key=lambda h: p_imp[h])
    order_exp = sorted(range(n), key=lambda h: -p_exp[h])
    cheap = set(order_imp[:max(1, n // 6)])
    peak = set(order_exp[:max(1, n // 8)]) if allow_grid_discharge else set()

    # očekávaný budoucí přebytek FVE (nech pro něj v baterii místo -> nenabíjej zbytečně z gridu)
    future_surplus = [0.0] * n
    acc = 0.0
    for h in range(n - 1, -1, -1):
        future_surplus[h] = acc
        acc += max(0.0, pv[h] - load[h])

    def grid_charge_cap(h):
        return max(floor, cap_kwh - future_surplus[h])

    out = []
    for h in range(n):
        surplus = pv[h] - load[h]
        chg = dis = imp = exp = 0.0
        action, reason = "idle", "self-use"

        if surplus > 0:
            room = cap_kwh - soc
            chg = min(surplus, room, max_charge_kwh)
            soc += chg
            exp = surplus - chg
            action = "charge_pv" if chg > 0 else ("export" if exp > 0 else "idle")
            reason = f"přebytek FVE {surplus:.1f} kWh"
            if h in cheap and soc < grid_charge_cap(h):           # dofoukni levně z gridu (s místem pro FVE)
                extra = min(grid_charge_cap(h) - soc, max_charge_kwh - chg)
                if extra > 0.05:
                    soc += extra; imp += extra; chg += extra
                    action = "charge_grid"; reason += f" + levné nabití {extra:.1f}"
        else:
            deficit = -surplus
            if h in peak and soc > floor:                        # špička → do sítě
                to_load = min(deficit, soc - floor, max_discharge_kwh)
                soc -= to_load; imp += deficit - to_load
                to_grid = min(max(0.0, soc - floor), max_discharge_kwh - to_load)
                soc -= to_grid; exp += to_grid; dis = to_load + to_grid
                action = "discharge_grid"; reason = f"špička: do sítě {to_grid:.1f} kWh"
            elif h in cheap and soc < grid_charge_cap(h):        # levné okno → nabíjej z gridu
                extra = min(grid_charge_cap(h) - soc, max_charge_kwh)
                soc += extra; imp += deficit + extra; chg = extra
                action = "charge_grid"; reason = f"levné okno: nabití {extra:.1f} kWh"
            else:                                                # self-use
                to_load = min(deficit, max(0.0, soc - floor), max_discharge_kwh)
                soc -= to_load; imp += deficit - to_load; dis = to_load
                action = "discharge_load" if to_load > 0 else "import"

        soc = _clamp(soc, 0.0, cap_kwh)
        out.append({
            "ts": ts[h], "action": action,
            "battery_kw": round(chg - dis, 3),                   # + nabíjení / − vybíjení
            "soc_pct": round(soc / cap_kwh * 100.0, 1) if cap_kwh else 0.0,
            "soc_kwh": round(soc, 2),
            "import_kwh": round(imp, 3), "export_kwh": round(exp, 3),
            "price_import": p_imp[h], "price_export": p_exp[h],
            "reason": reason,
        })
    return out
