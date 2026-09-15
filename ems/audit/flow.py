"""🔎 Audit hodnot schématu: pro každou zobrazenou hodnotu přesný vzorec, zdrojové metriky,
zařízení, registry (a jejich význam z manuálu) a surové hodnoty s časem. Používá tytéž
výpočty jako aggregate_now (vzorce jsou zde vypsané doslovně)."""
from __future__ import annotations

from datetime import datetime, timezone

from ems.api.db import aggregate_now, get_pool, list_devices
from .registers import METRIC_SOURCE, SOLIS_INPUT, SOLIS_HOLDING, describe

_METRICS = ["pv_power", "energy_today", "energy_pv_total", "grid_power", "battery_power", "battery_power_1",
            "battery_power_2", "battery_soc", "battery_soc_1", "battery_soc_2", "battery_voltage_1", "battery_voltage_2",
            "battery_current_1", "battery_current_2", "inverter_state", "temperature"]


async def _latest_samples(device_ids: list[str]) -> dict[str, dict[str, dict]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT ON (device_id, metric) device_id, metric, value, time FROM samples "
            "WHERE device_id = ANY($1::text[]) AND metric = ANY($2::text[]) AND time > now() - interval '15 minutes' "
            "ORDER BY device_id, metric, time DESC", device_ids, _METRICS)
    out: dict[str, dict[str, dict]] = {}
    for r in rows:
        out.setdefault(r["device_id"], {})[r["metric"]] = {"value": float(r["value"]), "ts": r["time"].isoformat()}
    return out


def _src(dev: str, metric: str, samples: dict) -> dict:
    s = (samples.get(dev) or {}).get(metric) or {}
    reg, how = METRIC_SOURCE.get(metric, ("?", "?"))
    return {"device": dev, "metric": metric, "value": s.get("value"), "ts": s.get("ts"), "register": reg, "decode": how}


async def build_audit(locality_id: int) -> dict:
    devs = [d for d in await list_devices() if d.get("locality_id") == locality_id]
    ids = [d["device_id"] for d in devs]
    solis = [d["device_id"] for d in devs if d.get("adapter") == "solis"]
    agg = await aggregate_now(ids) if ids else {}
    samples = await _latest_samples(ids) if ids else {}
    V: dict[str, dict] = {}

    def add(key, value, unit, formula, sources, note=None):
        V[key] = {"value": value, "unit": unit, "formula": formula, "sources": sources, **({"note": note} if note else {})}

    add("pv_w", agg.get("pv_w"), "W", "pv_w = Σ pv_power všech zařízení lokality (poslední vzorek ≤ 15 min)",
        [_src(d, "pv_power", samples) for d in solis])
    add("grid_w", agg.get("grid_w"), "W",
        "grid_w = Σ grid_power; grid_power = −(registr 33130 s32) → + odběr ze sítě, − dodávka do sítě",
        [_src(d, "grid_power", samples) for d in solis])
    bsrc = []
    for d in solis:
        bsrc += [_src(d, "battery_power", samples), _src(d, "battery_power_1", samples), _src(d, "battery_power_2", samples),
                 _src(d, "battery_voltage_1", samples), _src(d, "battery_current_1", samples),
                 _src(d, "battery_voltage_2", samples), _src(d, "battery_current_2", samples)]
    add("battery_w", agg.get("battery_w"), "W",
        "battery_w = Σ battery_power; battery_power = battery_power_1 + battery_power_2; "
        "battery_power_N = voltage_N × current_N × (−1 když direction_N = 1 vybíjení); + nabíjení / − vybíjení",
        bsrc, note="Proud packů je MAGNITUDA (registry 33134/34290 vždy +); znaménko dává směrový registr. "
                   "Křížová kontrola: registr 33149 (výkon baterie dle měniče) — ten EMS nepoužívá.")
    add("load_w", agg.get("load_w"), "W",
        "load_w = pv_w + grid_w − battery_w  (energetická bilance uzlu; záporný výsledek se ořízne na 0)",
        [{"derived_from": ["pv_w", "grid_w", "battery_w"]}],
        note="Spotřeba domu NENÍ měřená — je dopočítaná. Chyba v kterémkoli ze tří vstupů se promítne sem. "
             "Křížová kontrola: registr 33147 (zátěž domu dle měniče).")
    add("soc", agg.get("soc"), "%", "soc = průměr battery_soc zařízení; battery_soc = průměr SoC packů (33139, 34278)",
        [_src(d, m, samples) for d in solis for m in ("battery_soc", "battery_soc_1", "battery_soc_2")])
    add("today_kwh", agg.get("today_kwh"), "kWh",
        "today_kwh = Σ energy_today (čítač měniče 33035, ≤ 15 min starý); fallback max−min energy_pv_total za dnešek",
        [_src(d, "energy_today", samples) for d in solis])
    add("import_kwh", agg.get("import_kwh"), "kWh",
        "import_kwh = Σ max(grid_power, 0) × Δt / 3,6e6 přes vzorky od půlnoci (Δt do dalšího vzorku, ignoruje mezery > 120 s)",
        [{"derived_from": ["grid_power vzorky dnes"]}])
    add("export_kwh", agg.get("export_kwh"), "kWh",
        "export_kwh = Σ max(−grid_power, 0) × Δt / 3,6e6 přes vzorky od půlnoci (mezery > 120 s ignorovány)",
        [{"derived_from": ["grid_power vzorky dnes"]}])
    add("cons_today_kwh", agg.get("cons_today_kwh"), "kWh",
        "cons_today_kwh = today_kwh + import_kwh − export_kwh − bat_net_kwh; bat_net_kwh = ∫ battery_power dnes (+ nabíjení)",
        [{"derived_from": ["today_kwh", "import_kwh", "export_kwh", "battery_power vzorky dnes"]}],
        note="Dopočet; každá chyba v battery_power (např. špatný proud packu) se sem propíše.")

    # řídicí logika: kdo drží baterii, jaké parametry, čítač povelů
    control = {}
    try:
        from ems.control import db as control_db
        control["states"] = await control_db.get_states(solis) if solis else {}
    except Exception as exc:
        control["states_error"] = str(exc)
    try:
        from ems.planner import db as planner_db
        cfg = await planner_db.get_config(locality_id) or {}
        control["planner"] = {k: cfg.get(k) for k in ("enabled", "grid_charge_enabled", "neg_price_charge_enabled",
                                                     "neg_price_threshold_czk", "max_charge_kw", "max_discharge_kw",
                                                     "grid_export_limit_kw", "soc_min_pct", "capacity_kwh")}
        control["planner_action"] = await planner_db.current_action(locality_id)
    except Exception as exc:
        control["planner_error"] = str(exc)
    try:
        from ems.outputs import db as outputs_db
        control["outputs"] = [{k: o.get(k) for k in ("id", "name", "is_on", "last_decision", "last_action_at")}
                              for o in await outputs_db.list_all() if o.get("locality_id") == locality_id]
    except Exception as exc:
        control["outputs_error"] = str(exc)

    return {"generated_at": datetime.now(timezone.utc).isoformat(), "locality_id": locality_id,
            "devices": [{"id": d["device_id"], "adapter": d.get("adapter"), "type": d.get("device_type"),
                         "emsbox_id": d.get("emsbox_id")} for d in devs],
            "values": V, "control": control,
            "registers": {"input": {a: describe(a) for a in SOLIS_INPUT}, "holding": {a: describe(a) for a in SOLIS_HOLDING}}}


def to_markdown(a: dict, extra: dict | None = None) -> str:
    L = [f"# 🔎 TERA EMS audit — lokalita {a['locality_id']} — {a['generated_at']}", ""]
    L += ["## Zařízení"] + [f"- {d['id']} · {d['adapter']} · {d['type']} · box {d.get('emsbox_id') or '— (server)'}" for d in a["devices"]] + [""]
    L.append("## Hodnoty schématu (vzorec → zdroje)")
    for k, v in a["values"].items():
        L.append(f"### {k} = {v['value']} {v['unit']}")
        L.append(f"- vzorec: `{v['formula']}`")
        if v.get("note"):
            L.append(f"- poznámka: {v['note']}")
        for s in v["sources"]:
            if "derived_from" in s:
                L.append(f"- odvozeno z: {', '.join(s['derived_from'])}")
            else:
                L.append(f"- {s['device']} · {s['metric']} = **{s['value']}** @ {s['ts']} · registr {s['register']} · {s['decode']}")
        L.append("")
    L.append("## Řídicí logika (snapshot)")
    import json
    L.append("```json"); L.append(json.dumps(a["control"], ensure_ascii=False, indent=2, default=str)); L.append("```")
    if extra:
        L.append("## Časová pravidla — kontrola s realitou")
        L.append("```json"); L.append(json.dumps(extra, ensure_ascii=False, indent=2, default=str)); L.append("```")
    L.append("## Registry (význam podle manuálu)")
    L += [f"- {v}" for v in a["registers"]["input"].values()] + [f"- {v}" for v in a["registers"]["holding"].values()]
    return "\n".join(L)
