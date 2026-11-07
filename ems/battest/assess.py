"""Vyhodnocení testu baterie po blocích a článcích.

Pořadí pravidel (zkalibrováno na testu #1, 5. 11. 2026 — B1 ≈ polovina využitelné kapacity B2):
 1. využitelná energie bloku vs. jmenovitá (SoH bloku) — rozhodující,
 2. asymetrie bloků: blok zastaví nabíjení/vybíjení (P → 0), zatímco druhý je o ≥ 10 % SoC jinde → blok omezuje systém,
 3. omezující článek: max v okamžiku zastavení nabíjení (shora) / min v okamžiku zastavení vybíjení (zdola) + stálost extrému,
 4. Δ článků v kolenech pod zátěží (nahoře SoC ≥ 85 %, dole ≤ 20 %),
 5. Δ v klidu a na plató jen informativně (LFP plató rozdíly maskuje).
Prahy jsou v THRESHOLDS — jediné místo k ladění."""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime

from ems.api.db import get_pool

THRESHOLDS = {
    "soh_amber": 85.0, "soh_red": 70.0,                 # % jmenovité kapacity
    "asym_amber": 5.0, "asym_red": 10.0,                # rozdíl SoC bloků při zastavení jednoho (%)
    "share_amber": 50.0, "share_red": 75.0,             # podíl minut, kdy je tentýž článek extrémem (%)
    "knee_top_amber": 120, "knee_top_red": 200,         # Δ mV nahoře pod zátěží (LFP koleno: zdravý blok B2 mělo 151 mV)
    "plateau_amber": 40,                                # Δ mV na plató pod zátěží — nad tím se stálý extrém počítá jako odpor
    "rest_settle_min": 20,                              # klid = bez proudu aspoň N minut (relaxace napětí)
    "knee_bot_amber": 60, "knee_bot_red": 100,          # Δ mV dole pod zátěží
    "eff_amber": 90.0,                                  # účinnost celku %
    "jump_ratio": 0.5,                                  # krok 10 % SoC s < 50 % mediánu kWh zdravých kroků = skok SoC BMS
    "window_amber": 0.85, "window_red": 0.7,            # využitelná ÷ kapacita lineární části
    "p_active_w": 500, "p_rest_w": 100,                 # kdy je blok „pod zátěží“ / „v klidu“
    "p_stopped_w": 150, "p_other_w": 1000,              # blok zastavil × druhý jede
}
LEVEL_ORDER = {"green": 0, "amber": 1, "red": 2}
LEVEL_TXT = {"green": "🟢 v pořádku", "amber": "🟡 sledovat", "red": "🔴 pozornost / výměna"}


def cell_txt(n, cpm) -> str:
    if n is None:
        return "?"
    n = int(round(n))
    if cpm and cpm > 0:
        cpm = int(round(cpm))
        return f"článek {n} (modul {(n - 1) // cpm + 1}, poz. {(n - 1) % cpm + 1})"
    return f"článek {n}"


def _worse(a: str, b: str) -> str:
    return a if LEVEL_ORDER[a] >= LEVEL_ORDER[b] else b


async def series_cells(device_id: str, t0: datetime, t1: datetime, packs: list[int]) -> list[dict]:
    """Po minutě: pro každý pack SoC, výkon, článek min/max V a jejich čísla, článků na modul."""
    metrics = []
    for k in packs:
        metrics += [f"battery_soc_{k}", f"battery_power_{k}", f"battery_cell_vmin_{k}", f"battery_cell_vmax_{k}",
                    f"battery_cell_nmin_{k}", f"battery_cell_nmax_{k}", f"battery_bms_cells_per_module_{k}"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT time_bucket('1 minute', time) AS t, metric, avg(value) AS v
            FROM samples WHERE device_id=$1 AND metric = ANY($2::text[]) AND time >= $3::timestamptz AND time <= $4::timestamptz
            GROUP BY t, metric ORDER BY t""", device_id, metrics, t0, t1)
    out: dict[datetime, dict] = {}
    for r in rows:
        out.setdefault(r["t"], {"ts": r["t"]})[r["metric"]] = float(r["v"])
    return [out[k] for k in sorted(out)]


def _window(marks: list[dict], phase: str, t_end: datetime) -> tuple[datetime, datetime] | None:
    for i, m in enumerate(marks):
        if m["phase"] == phase:
            a = datetime.fromisoformat(m["ts"])
            b = datetime.fromisoformat(marks[i + 1]["ts"]) if i + 1 < len(marks) else t_end
            return a, b
    return None


def _energy(rows: list[dict], key: str, sign: int) -> float:
    """kWh z minutových průměrů výkonu (W); sign +1 nabíjení, −1 vybíjení."""
    return sum(max(0.0, sign * r[key]) for r in rows if r.get(key) is not None) / 60.0 / 1000.0


def _soc_bounds(rows: list[dict], k: int, key_p: str, sign: int) -> tuple[float | None, float | None, datetime | None]:
    """SoC bloku na začátku okna a v okamžiku, kdy blok přestal pracovat (P ≈ 0) nebo na konci okna."""
    act = [r for r in rows if r.get(f"battery_soc_{k}") is not None]
    if not act:
        return None, None, None
    s0 = act[0][f"battery_soc_{k}"]
    stop = None
    seen_active = False
    for r in act:
        p = sign * (r.get(key_p) or 0)
        if p > THRESHOLDS["p_active_w"]:
            seen_active = True
        elif seen_active and p < THRESHOLDS["p_stopped_w"]:
            stop = r; break
    end = stop or act[-1]
    return s0, end[f"battery_soc_{k}"], end["ts"]


def _share(rows: list[dict], key_n: str, cpm) -> list[dict]:
    c = Counter(int(round(r[key_n])) for r in rows if r.get(key_n) is not None and r[key_n] >= 0.5)   # 0 = BMS nehlásí
    n = sum(c.values()) or 1
    return [{"cell": cell, "txt": cell_txt(cell, cpm), "count": cnt, "share_pct": round(cnt / n * 100, 1)} for cell, cnt in c.most_common(3)]


def _soc_steps(rows: list[dict], k: int, sign: int) -> list[dict]:
    """kWh za každý 10% krok SoC bloku (podle BMS) v daném směru; cell = extrémní článek na konci kroku."""
    kp, ks = f"battery_power_{k}", f"battery_soc_{k}"
    out = []; last = None; e = 0.0; e0 = 0.0; t0 = None
    key_n = f"battery_cell_nmax_{k}" if sign > 0 else f"battery_cell_nmin_{k}"
    for r in rows:
        if r.get(ks) is None:
            continue
        e += max(0.0, sign * (r.get(kp) or 0)) / 60.0 / 1000.0
        s = int(r[ks] // 10) * 10
        if last is None:
            last, e0, t0 = s, e, r["ts"]; continue
        if s != last:
            cell = r.get(key_n)
            out.append({"from": last, "to": s, "kwh": round(e - e0, 2), "t_from": t0.isoformat(), "t_to": r["ts"].isoformat(),
                        "minutes": round((r["ts"] - t0).total_seconds() / 60), "cell": int(round(cell)) if cell is not None and cell >= 0.5 else None})
            last, e0, t0 = s, e, r["ts"]
    return [x for x in out if (x["to"] - x["from"]) == 10 * sign]


def _delta_stats(rows: list[dict], k: int, pred) -> dict:
    d = [(r[f"battery_cell_vmax_{k}"] - r[f"battery_cell_vmin_{k}"]) * 1000 for r in rows
         if r.get(f"battery_cell_vmax_{k}") is not None and r.get(f"battery_cell_vmin_{k}") is not None and pred(r)]
    if not d:
        return {"n": 0}
    return {"n": len(d), "median_mv": round(statistics.median(d)), "p90_mv": round(sorted(d)[int(0.9 * (len(d) - 1))]), "max_mv": round(max(d))}


async def assess(t: dict, result: dict | None = None) -> dict:
    """Vyhodnocení dokončeného (nebo přerušeného) testu. t musí nést phase_marks, params, module_id, started_at, ended_at."""
    T = THRESHOLDS
    p = t["params"]
    blocks = p.get("blocks") or []
    t0 = datetime.fromisoformat(t["started_at"]); t1 = datetime.fromisoformat(t["ended_at"]) if t.get("ended_at") else datetime.now(t0.tzinfo)
    marks = t.get("phase_marks") or []
    packs = [int(b["idx"]) for b in blocks] or [1, 2]
    rows = await series_cells(t["module_id"], t0, t1, packs)
    present = [k for k in packs if any(r.get(f"battery_soc_{k}") is not None for r in rows)]
    if not blocks:   # starší test bez bloků v parametrech → aktuální bloky modulu, jinak jmenovitá ÷ počet packů
        from . import blocks as blocks_mod
        blocks = await blocks_mod.blocks_for_test(t["module_id"], float(p.get("capacity_kwh") or 0), len(present) or 1)
        blocks = [b for b in blocks if int(b["idx"]) in present] or blocks
    w_chg = _window(marks, "charge", t1); w_hold = _window(marks, "hold", t1); w_dis = _window(marks, "discharge", t1)
    def rows_in(w):
        return [r for r in rows if w and w[0] <= r["ts"] <= w[1]] if w else []
    r_chg, r_hold, r_dis = rows_in(w_chg), rows_in(w_hold), rows_in(w_dis)
    out = {"level": "green", "blocks": [], "findings": [], "thresholds": T, "nominal_total_kwh": float(p.get("capacity_kwh") or 0)}
    ceil, floor = float(p.get("ceil_pct") or 100), float(p.get("floor_pct") or 10)

    for k in present:
        b = next((x for x in blocks if int(x["idx"]) == k), {"idx": k, "name": f"B{k}", "capacity_kwh": None})
        kp, ks = f"battery_power_{k}", f"battery_soc_{k}"
        cpm = next((r.get(f"battery_bms_cells_per_module_{k}") for r in rows if r.get(f"battery_bms_cells_per_module_{k}")), None)
        res = {"idx": k, "name": b.get("name") or f"B{k}", "nominal_kwh": b.get("capacity_kwh"), "module_model": b.get("module_model"),
               "modules_count": b.get("modules_count"), "installed": b.get("installed"), "note": b.get("note"), "cells_per_module": cpm,
               "level": "green", "findings": [], "limits": [], "cells": {}}
        # energie
        res["e_chg_kwh"] = round(_energy(r_chg, kp, +1), 2)
        res["e_hold_kwh"] = round(_energy(r_hold, kp, +1), 2)
        res["e_dis_kwh"] = round(_energy(r_dis, kp, -1), 2)
        s0c, s1c, _ = _soc_bounds(r_chg, k, kp, +1)
        s0d, s1d, ts_stop_d = _soc_bounds(r_dis, k, kp, -1)
        res["soc_chg_from"], res["soc_chg_to"] = s0c, s1c
        res["soc_dis_from"], res["soc_dis_to"] = s0d, s1d
        # 1. využitelná kapacita a SoH bloku (z vybíjení přes skutečně projetý rozsah SoC bloku)
        if res["e_dis_kwh"] > 0 and s0d is not None and s1d is not None and s0d - s1d >= 20:
            cap = res["e_dis_kwh"] / ((s0d - s1d) / 100.0)
            res["capacity_est_kwh"] = round(cap, 2)
            if b.get("capacity_kwh"):
                soh = cap / float(b["capacity_kwh"]) * 100
                res["soh_pct"] = round(soh, 1)
                lvl = "red" if soh < T["soh_red"] else "amber" if soh < T["soh_amber"] else "green"
                res["findings"].append({"level": lvl, "rule": "soh",
                    "text": f"Využitelná kapacita {cap:.2f} kWh z jmenovitých {float(b['capacity_kwh']):.2f} kWh → SoH {soh:.1f} % "
                            f"(vybito {res['e_dis_kwh']:.2f} kWh mezi {s0d:.0f} a {s1d:.0f} % SoC bloku)."
                            + (" Nad jmenovitou hodnotou: nové články mívají rezervu, SoC škála BMS není přesně lineární." if soh > 100 else "")})
                res["level"] = _worse(res["level"], lvl)
        if res["e_chg_kwh"] > 0 and s0c is not None and s1c is not None and s1c - s0c >= 20:
            res["capacity_from_charge_kwh"] = round(res["e_chg_kwh"] / ((s1c - s0c) / 100.0), 2)
        # účinnost bloku jen při uzavřeném cyklu (SoC na začátku nabíjení ≈ SoC na konci vybíjení) a fyzikálně možná (≤ 100 %);
        # jinak jde o bilanci — a bilance „vybito > nabito“ je sama o sobě nález: BMS SoC bloku není konzistentní.
        e_in = res["e_chg_kwh"] + res["e_hold_kwh"]
        res["balance_pct"] = round(res["e_dis_kwh"] / e_in * 100, 1) if res["e_dis_kwh"] > 0 and e_in > 0 else None
        closed = s0c is not None and s1d is not None and abs(s0c - s1d) <= 2
        if res["balance_pct"] is not None and closed and res["balance_pct"] <= 100:
            res["efficiency_pct"] = res["balance_pct"]
        elif res["balance_pct"] is not None and res["balance_pct"] > 100:
            res["findings"].append({"level": "amber", "rule": "balance",
                "text": f"Bilance bloku: nabito {e_in:.2f} kWh, vybito {res['e_dis_kwh']:.2f} kWh — vybito více než nabito, což nejde; "
                        f"SoC bloku z BMS tedy není konzistentní (na začátku „{s0c:.0f} %“ bylo v bloku reálně víc energie než na konci „{s1d:.0f} %“). "
                        f"Typický projev BMS, které SoC koriguje podle napětí slabého článku. Využitelná kapacita bloku je proto odhad: "
                        f"{min(e_in, res['e_dis_kwh']):.2f}–{max(e_in, res['e_dis_kwh']):.2f} kWh (nabito / vybito) přes ~{(s0d - s1d) if s0d is not None and s1d is not None else 0:.0f} % SoC."})
            res["level"] = _worse(res["level"], "amber")
        # 1b. SoC skok: kroky po 10 % s výrazně menší energií než zdravé kroky → BMS SoC bloku „přeskakuje“ (pinned na extrémní článek);
        #     kapacita lineární části = medián zdravých kroků × 10 (co články mají), využitelná = co z nich pustí BMS.
        st_c = _soc_steps(r_chg, k, +1); st_d = _soc_steps(r_dis, k, -1)
        res["soc_steps"] = {"charge": st_c, "discharge": st_d}
        allsteps = [x for x in st_c + st_d if x["kwh"] > 0]
        if len(allsteps) >= 4:
            top = sorted(x["kwh"] for x in allsteps)[-max(3, len(allsteps) // 2):]
            healthy_med = statistics.median(top)
            jumps = [x for x in allsteps if x["kwh"] < T["jump_ratio"] * healthy_med]
            res["capacity_linear_kwh"] = round(healthy_med * 10, 2)
            res["jump_steps"] = jumps
            if jumps and res.get("capacity_est_kwh"):
                ratio = res["capacity_est_kwh"] / res["capacity_linear_kwh"]
                res["window_ratio"] = round(ratio, 3)
                lvl = "red" if ratio < T["window_red"] else "amber" if ratio < T["window_amber"] else "green"
                def zone(steps, lbl):
                    z = [x for x in jumps if x in steps]
                    if not z:
                        return None
                    lo, hi = min(min(x["from"], x["to"]) for x in z), max(max(x["from"], x["to"]) for x in z)
                    cells = Counter(x["cell"] for x in z if x["cell"] is not None)
                    c = cells.most_common(1)[0][0] if cells else None
                    return f"{lbl} {lo}–{hi} % ({sum(x['kwh'] for x in z):.2f} kWh na {len(z) * 10} % škály" + (f", vede {cell_txt(c, cpm)}" if c is not None else "") + ")"
                zones = [z for z in (zone(st_c, "nabíjení"), zone(st_d, "vybíjení")) if z]
                res["findings"].append({"level": lvl, "rule": "soc_jump",
                    "text": f"SoC bloku z BMS skáče: {'; '.join(zones)}. V lineární části škály dává blok {healthy_med:.2f} kWh na 10 % → "
                            f"články mají ≈ {res['capacity_linear_kwh']:.2f} kWh, ale BMS z nich pustí jen {res['capacity_est_kwh']:.2f} kWh ({ratio * 100:.0f} %). "
                            f"Okno zavírají jednotlivé články (viz omezující články), ne stárnutí všech — po výměně/vyvážení viníků lze čekat návrat k ≈ {res['capacity_linear_kwh']:.2f} kWh."})
                res["level"] = _worse(res["level"], lvl)
        # 2. asymetrie: blok zastaví, druhý jede
        others = [o for o in present if o != k]
        for direction, rws, sign, key_n, lbl in (("charge", r_chg, +1, f"battery_cell_nmax_{k}", "nabíjení"),
                                                 ("discharge", r_dis, -1, f"battery_cell_nmin_{k}", "vybíjení")):
            seen = False
            for r in rws:
                pk = sign * (r.get(kp) or 0)
                if pk > T["p_active_w"]:
                    seen = True; continue
                if not seen or pk > T["p_stopped_w"]:
                    continue
                po = max((sign * (r.get(f"battery_power_{o}") or 0) for o in others), default=0)
                if po < T["p_other_w"]:
                    continue
                s_k = r.get(ks); s_o = [r.get(f"battery_soc_{o}") for o in others if r.get(f"battery_soc_{o}") is not None]
                if s_k is None or not s_o:
                    continue
                target_ok = (s_k >= ceil - 1) if direction == "charge" else (s_k <= floor + 1)
                diff = max(abs(s_k - s) for s in s_o)
                lvl = "red" if diff >= T["asym_red"] else "amber" if diff >= T["asym_amber"] else "green"
                cell = r.get(key_n)
                if cell is not None and cell < 0.5:
                    cell = None
                res["limits"].append({"direction": direction, "ts": r["ts"].isoformat(), "soc": round(s_k, 1), "other_soc": round(s_o[0], 1),
                                      "diff_pct": round(diff, 1), "cell": int(round(cell)) if cell is not None else None,
                                      "cell_txt": cell_txt(cell, cpm) if cell is not None else None, "level": lvl,
                                      "vmin": r.get(f"battery_cell_vmin_{k}"), "vmax": r.get(f"battery_cell_vmax_{k}")})
                if lvl != "green":
                    side = "shora" if direction == "charge" else "zdola"
                    res["findings"].append({"level": lvl, "rule": "asym",
                        "text": f"Blok zastavil {lbl} při {s_k:.0f} % SoC, zatímco druhý blok byl na {s_o[0]:.0f} % (rozdíl {diff:.0f} %) → "
                                f"omezuje systém {side}" + (f"; v tom okamžiku {'nejvyšší' if direction == 'charge' else 'nejnižší'} {cell_txt(cell, cpm)} "
                                f"({(r.get(f'battery_cell_vmax_{k}') if direction == 'charge' else r.get(f'battery_cell_vmin_{k}')):.3f} V)." if cell is not None else ".")})
                    res["level"] = _worse(res["level"], lvl)
                break
        # 3. stálost extrémů (podíl minut)
        act_chg = [r for r in r_chg if (r.get(kp) or 0) > T["p_active_w"]]
        act_dis = [r for r in r_dis if (r.get(kp) or 0) < -T["p_active_w"]]
        rest = []
        quiet = 0
        for r in rows:
            quiet = quiet + 1 if abs(r.get(kp) or 0) < T["p_rest_w"] else 0
            if quiet >= T["rest_settle_min"] and r.get(ks) is not None:
                rest.append(r)
        res["cells"] = {"max_charge": _share(act_chg, f"battery_cell_nmax_{k}", cpm), "min_charge": _share(act_chg, f"battery_cell_nmin_{k}", cpm),
                        "min_discharge": _share(act_dis, f"battery_cell_nmin_{k}", cpm), "max_discharge": _share(act_dis, f"battery_cell_nmax_{k}", cpm),
                        "min_rest": _share(rest, f"battery_cell_nmin_{k}", cpm), "max_rest": _share(rest, f"battery_cell_nmax_{k}", cpm),
                        "minutes": {"charge": len(act_chg), "discharge": len(act_dis), "rest": len(rest)}}
        # 4. Δ v kolenech pod zátěží, 5. plató a klid informativně (počítá se dřív — rozhoduje o váze stálosti článků)
        res["delta"] = {"knee_top": _delta_stats(act_chg, k, lambda r: (r.get(ks) or 0) >= 85),
                        "knee_bottom": _delta_stats(act_dis, k, lambda r: (r.get(ks) or 0) <= 20),
                        "plateau_charge": _delta_stats(act_chg, k, lambda r: 30 <= (r.get(ks) or 0) <= 80),
                        "plateau_discharge": _delta_stats(act_dis, k, lambda r: 30 <= (r.get(ks) or 0) <= 80),
                        "rest": _delta_stats(rest, k, lambda r: True)}
        kt = res["delta"]["knee_top"].get("max_mv"); kb = res["delta"]["knee_bottom"].get("max_mv")
        plateau_mv = max(res["delta"]["plateau_charge"].get("median_mv") or 0, res["delta"]["plateau_discharge"].get("median_mv") or 0)
        spread_up = (kt or 0) >= T["knee_top_amber"] or (res["delta"]["plateau_charge"].get("median_mv") or 0) >= T["plateau_amber"]
        spread_dn = (kb or 0) >= T["knee_bot_amber"] or (res["delta"]["plateau_discharge"].get("median_mv") or 0) >= T["plateau_amber"]
        spread = spread_up or spread_dn
        top_max_chg = res["cells"]["max_charge"][0] if res["cells"]["max_charge"] else None
        top_min_dis = res["cells"]["min_discharge"][0] if res["cells"]["min_discharge"] else None
        flagged: dict[int, dict] = {}
        for item, role, sp in ((top_max_chg, "nejvyšší při nabíjení", spread_up), (top_min_dis, "nejnižší při vybíjení", spread_dn)):
            if not item or item["share_pct"] < T["share_amber"]:
                continue
            lvl = ("red" if item["share_pct"] >= T["share_red"] else "amber") if sp else "green"
            f = flagged.setdefault(item["cell"], {"cell": item["cell"], "txt": item["txt"], "roles": [], "level": "green"})
            f["roles"].append(f"{role} {item['share_pct']:.0f} % minut"); f["level"] = _worse(f["level"], lvl)
        both = (top_max_chg and top_min_dis and top_max_chg["cell"] == top_min_dis["cell"]
                and top_max_chg["share_pct"] >= T["share_amber"] and top_min_dis["share_pct"] >= T["share_amber"])
        if both and top_max_chg["cell"] in flagged:
            f = flagged[top_max_chg["cell"]]
            if spread:
                f["level"] = "red"; f["roles"].append("extrém v obou směrech → vysoký vnitřní odpor")
            else:
                f["roles"].append("extrém v obou směrech, ale rozptyl malý → bez dopadu")
        for lim in res["limits"]:
            if lim.get("cell") is not None:
                f = flagged.setdefault(lim["cell"], {"cell": lim["cell"], "txt": lim["cell_txt"], "roles": [], "level": "green"})
                f["roles"].append("omezil blok " + ("shora" if lim["direction"] == "charge" else "zdola")); f["level"] = _worse(f["level"], lim["level"])
        res["flagged_cells"] = sorted(flagged.values(), key=lambda x: -LEVEL_ORDER[x["level"]])
        for f in res["flagged_cells"]:
            if f["level"] == "green":
                res["findings"].append({"level": "green", "rule": "cell", "text": f"{f['txt'].capitalize()} — {', '.join(f['roles'])}; rozptyl článků malý (plató {plateau_mv} mV) → bez dopadu, jen evidence."})
                continue
            verdict = "na výměnu / reklamaci" if f["level"] == "red" else "sledovat"
            res["findings"].append({"level": f["level"], "rule": "cell", "text": f"{f['txt'].capitalize()} — {', '.join(f['roles'])} → {verdict}."})
            res["level"] = _worse(res["level"], f["level"])
        # modul s více označenými články
        if cpm:
            mods = Counter((f["cell"] - 1) // int(round(cpm)) + 1 for f in res["flagged_cells"] if f["level"] != "green")
            for mod, cnt in mods.items():
                if cnt >= 2:
                    res["findings"].append({"level": "red", "rule": "module", "text": f"Modul {mod}: {cnt} označené články → kandidát na výměnu celého modulu."})
                    res["level"] = "red"
        if kt is not None and kt >= T["knee_top_amber"]:
            lvl = "red" if kt >= T["knee_top_red"] else "amber"
            res["findings"].append({"level": lvl, "rule": "knee_top", "text": f"Rozptyl článků nahoře pod zátěží až {kt} mV (SoC ≥ 85 %)."})
            res["level"] = _worse(res["level"], lvl)
        if kb is not None and kb >= T["knee_bot_amber"]:
            lvl = "red" if kb >= T["knee_bot_red"] else "amber"
            res["findings"].append({"level": lvl, "rule": "knee_bottom", "text": f"Rozptyl článků dole pod zátěží až {kb} mV (SoC ≤ 20 %)."})
            res["level"] = _worse(res["level"], lvl)
        if not res["findings"]:
            res["findings"].append({"level": "green", "rule": "ok", "text": "Bez nálezu: energie odpovídá jmenovité kapacitě, žádný stálý extrémní článek."})
        res["findings"].sort(key=lambda f: -LEVEL_ORDER[f["level"]])
        out["blocks"].append(res)
        out["level"] = _worse(out["level"], res["level"])

    # celek
    if result:
        eff = result.get("efficiency_pct")
        if eff is not None and eff < T["eff_amber"]:
            out["findings"].append({"level": "amber", "rule": "efficiency", "text": f"Účinnost cyklu {eff} % je pod {T['eff_amber']:g} %."})
            out["level"] = _worse(out["level"], "amber")
    if len(out["blocks"]) >= 2:
        caps = [b.get("capacity_est_kwh") for b in out["blocks"] if b.get("capacity_est_kwh")]
        if len(caps) >= 2 and min(caps) > 0:
            ratio = (max(caps) - min(caps)) / max(caps) * 100
            weakest = min(out["blocks"], key=lambda b: b.get("capacity_est_kwh") or 1e9)
            if ratio >= 10:
                out["findings"].append({"level": "red" if ratio >= 25 else "amber", "rule": "blocks",
                    "text": f"Bloky se liší využitelnou kapacitou o {ratio:.0f} % — nejslabší {weakest['name']} ({weakest['capacity_est_kwh']:.2f} kWh). "
                            f"Měnič sdílí výkon podle SoC, slabší blok tedy omezuje využitelnou kapacitu celku."})
                out["level"] = _worse(out["level"], "red" if ratio >= 25 else "amber")
    out["summary"] = _summary(out)
    return out


def _summary(a: dict) -> str:
    parts = []
    for b in a["blocks"]:
        s = f"{b['name']}: {LEVEL_TXT[b['level']]}"
        if b.get("soh_pct") is not None:
            s += f" — SoH {b['soh_pct']} % ({b['capacity_est_kwh']:.2f} kWh)"
        bad = [f["text"] for f in b["findings"] if f["level"] == "red"]
        if bad:
            s += "; " + " ".join(bad)
        parts.append(s)
    for f in a["findings"]:
        parts.append(f["text"])
    return "\n".join(parts)
