"""API plánovače: konfigurace (per lokalita) + plán + ruční přepočet."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db as pdb
from . import service

router = APIRouter(prefix="/api/planner", tags=["planner"])
read = require_permission("read")
control = require_permission("control")


class PlannerConfigIn(BaseModel):
    grid_charge_enabled: bool | None = None
    neg_price_charge_enabled: bool | None = None
    neg_price_threshold_czk: float | None = None
    enabled: bool | None = None
    allow_grid_discharge: bool | None = None
    capacity_kwh: float | None = None
    soc_min_pct: float | None = None
    outage_reserve_pct: float | None = None
    max_charge_kw: float | None = None
    max_discharge_kw: float | None = None
    horizon_h: int | None = None
    spiral_output_id: int | None = None
    spiral_target_kwh: float | None = None
    spiral_deadline_h: int | None = None
    spiral_power_kw: float | None = None
    spiral_tmax_metric: str | None = None
    spiral_tmax_c: float | None = None
    spiral_kwh_per_deg: float | None = None
    spiral_min_on_min: int | None = None
    spiral_min_off_min: int | None = None
    spiral_anti_curtail: bool | None = None
    spiral_curtail_frac: float | None = None
    breaker_kw: float | None = None
    cycle_margin_czk_kwh: float | None = None
    grid_export_limit_kw: float | None = None
    dso_export_limit_kw: float | None = None
    export_price_floor_czk: float | None = None
    import_price_ceiling_czk: float | None = None
    reserve_margin_pct: float | None = None
    priority_order: str | None = None
    hodnota_tepla_leto: float | None = None
    season_mode: str | None = None
    prah_zima: float | None = None
    prah_leto: float | None = None
    tc_prikon_kw: float | None = None
    tc_tuv_kwh_den: float | None = None
    tc_cop_a: float | None = None
    tc_cop_b: float | None = None
    tc_cop_min: float | None = None
    tc_cop_max: float | None = None


@router.get("/controlled/devices")
async def controlled(_: dict = Depends(read)):
    """device_id moduly, které právě řídí zapnutý plánovač (pro UI precedenci)."""
    by_loc = await service.controlled_devices()
    return {"devices": [d for ds in by_loc.values() for d in ds]}


@router.get("/{locality_id}/amplitudes")
async def amplitudes(locality_id: int, spiral_target_kwh: float | None = None,
                     spiral_power_kw: float = 6.0, spiral_deadline_h: int = 7,
                     breaker_kw: float = 22.0, max_windows: int = 4,
                     threshold_pct: float = 33.0, _: dict = Depends(read)):
    """Spodní/horní amplitudy na efektivní ceně (valley/peak okna) + volitelný plán 6 kW spirály.
    spiral_target_kwh > 0 → vrátí i naplánované běhy spirály (PV přebytek → nejlevnější valley)."""
    return await service.amplitudes(
        locality_id, spiral_target_kwh=spiral_target_kwh, spiral_power_kw=spiral_power_kw,
        spiral_deadline_h=spiral_deadline_h, breaker_kw=breaker_kw,
        max_windows=max_windows, threshold_pct=threshold_pct)


@router.get("/{locality_id}")
async def get_plan(locality_id: int, _: dict = Depends(read)):
    return {
        "config": await pdb.get_config(locality_id),
        "schedule": await pdb.latest_schedule(locality_id),
        "current": await pdb.current_action(locality_id),
    }


@router.put("/{locality_id}/config")
async def put_config(locality_id: int, body: PlannerConfigIn, user: dict = Depends(control)):
    data = body.model_dump(exclude_unset=True)
    # Audit přepínače nabíjení ze sítě (brief §3.2): kdo a kdy ho změnil
    if "grid_charge_enabled" in data:
        try:
            old = (await pdb.get_config(locality_id) or {}).get("grid_charge_enabled")
            if old is not None and bool(old) != bool(data["grid_charge_enabled"]):
                from ems.alerts import db as alerts_db
                from ems.notify import dispatch as notify_dispatch
                stav = "ZAPNUTO" if data["grid_charge_enabled"] else "VYPNUTO"
                await alerts_db.record_event(locality_id, "config",
                    "Nabíjení baterie ze sítě (levný spot)",
                    f"{stav} · uživatel {user.get('username', '?')}")
                await notify_dispatch.notify_new_alerts()
        except Exception:
            pass
    if "neg_price_charge_enabled" in data:   # (c): samostatný vypínač záporné ceny — audit
        try:
            old = (await pdb.get_config(locality_id) or {}).get("neg_price_charge_enabled")
            if old is not None and bool(old) != bool(data["neg_price_charge_enabled"]):
                from ems.alerts import db as alerts_db
                from ems.notify import dispatch as notify_dispatch
                stav = "ZAPNUTO" if data["neg_price_charge_enabled"] else "VYPNUTO"
                await alerts_db.record_event(locality_id, "config",
                    "Nabíjení baterie při záporné ceně",
                    f"{stav} · uživatel {user.get('username', '?')}")
                await notify_dispatch.notify_new_alerts()
        except Exception:
            pass
    cfg = await pdb.upsert_config(locality_id, data)
    # po změně rovnou přepočítej plán
    try:
        await service.run_locality(locality_id)
    except Exception:
        pass
    return {"config": cfg}


@router.post("/{locality_id}/refresh")
async def refresh(locality_id: int, _: dict = Depends(control)):
    res = await service.run_locality(locality_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "přepočet selhal"))
    return res


class TimeRuleIn(BaseModel):
    enabled: bool | None = True
    label: str | None = ""
    time_from: str | None = None
    time_to: str | None = None
    days: str | None = "1234567"
    action: str | None = None
    target: str | None = None
    power_kw: float | None = 5.0
    cond_sun: str | None = None
    cond_sun_kwh: float | None = None
    cond_sun_day: str | None = None
    cond_soc_op: str | None = None
    cond_soc_pct: float | None = None
    cond_spot_op: str | None = None
    cond_spot_czk: float | None = None
    cond_spot_hold: bool | None = None
    cond_logic: str | None = None
    cond_soc_hold: bool | None = None


def _validate_rule(body: TimeRuleIn, require_all: bool) -> dict:
    d = body.model_dump()
    if d.get("action") is not None and d["action"] not in pdb.TIME_RULE_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action musí být jedno z {pdb.TIME_RULE_ACTIONS}")
    for k in ("time_from", "time_to"):
        v = d.get(k)
        if v is not None:
            import re
            if not re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", v):
                raise HTTPException(status_code=400, detail=f"{k} musí být HH:MM")
    if d.get("days") is not None and (not d["days"] or any(c not in "1234567" for c in d["days"])):
        raise HTTPException(status_code=400, detail="days = číslice 1–7 (Po–Ne)")
    if require_all and (not d.get("action") or not d.get("time_from") or not d.get("time_to")):
        raise HTTPException(status_code=400, detail="action, time_from a time_to jsou povinné")
    if d.get("action") in ("output_on", "output_off") and require_all and not d.get("target"):
        raise HTTPException(status_code=400, detail="u spínání spotřebiče vyber výstup (target)")
    if d.get("cond_sun") is not None and d["cond_sun"] not in ("any", "sunny", "cloudy"):
        raise HTTPException(status_code=400, detail="cond_sun: any|sunny|cloudy")
    if d.get("cond_sun_day") is not None and d["cond_sun_day"] not in ("today", "tomorrow"):
        raise HTTPException(status_code=400, detail="cond_sun_day: today|tomorrow")
    if d.get("cond_soc_op") is not None and d["cond_soc_op"] not in ("any", "ge", "le"):
        raise HTTPException(status_code=400, detail="cond_soc_op: any|ge|le")
    if d.get("cond_spot_op") is not None and d["cond_spot_op"] not in ("any", "ge", "le"):
        raise HTTPException(status_code=400, detail="cond_spot_op: any|ge|le")
    if d.get("cond_logic") is not None and d["cond_logic"] not in ("and", "or"):
        raise HTTPException(status_code=400, detail="cond_logic: and|or")
    return d


@router.get("/{locality_id}/time-rules")
async def list_time_rules(locality_id: int, _: dict = Depends(require_permission("read"))):
    return await pdb.list_time_rules(locality_id)


@router.get("/{locality_id}/time-rules/check")
async def check_time_rules(locality_id: int, _: dict = Depends(require_permission("read"))):
    """🔍 Kontrola pravidel s REALITOU: pro každé pravidlo okno/den/zapnuto + každá podmínka
    s aktuální hodnotou a prahem + verdikt „spustilo by se TEĎ". Stejné vstupy a stejné
    funkce jako collector (rule_conditions_explain), takže výsledek = co engine udělá."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/Prague"))
    hm, isoday = now.strftime("%H:%M"), str(now.isoweekday())
    rules = await pdb.list_time_rules(locality_id)
    # vstupy reality (stejné zdroje jako collector)
    devs = (await service.controlled_devices()).get(locality_id, [])
    soc_now = None
    try:
        soc_now = await service._soc_now(devs) if devs else None
    except Exception:
        pass
    spot_kwh = None
    try:
        from ems.outputs.engine import _spot_price
        sp = await _spot_price()
        spot_kwh = float(sp) / 1000.0 if sp is not None else None
    except Exception:
        pass
    day_pv = {}
    try:
        t0 = now.date()
        for e in (await service.pv_forecast_days_kwh(locality_id)) or []:
            if e["day"] == t0.isoformat():
                day_pv["today"] = e["kwh"]
            elif e["day"] == (t0 + timedelta(days=1)).isoformat():
                day_pv["tomorrow"] = e["kwh"]
    except Exception:
        pass
    # kdo teď drží řízení baterie
    holder = None
    try:
        from ems.control import db as control_db
        sts = await control_db.get_states(devs) if devs else {}
        for d, st in (sts or {}).items():
            holder = {"device": d, "source": st.get("source"), "action": st.get("action")}
            break
    except Exception:
        pass
    out, winner_batt = [], None
    for rule in rules:
        wk = pdb.rule_window_key(rule)
        win_ok = pdb._rule_active({**rule, "enabled": True}, hm, isoday)
        day_ok = isoday in (rule.get("days") or "1234567")
        latched = ((rule.get("cond_spot_op") or "any") != "any" and not rule.get("cond_spot_hold", True)
                   and rule.get("latched_window") == wk)
        soc_latched = ((rule.get("cond_soc_op") or "any") != "any" and not rule.get("cond_soc_hold", True)
                       and rule.get("latched_soc_window") == wk)
        ev = pdb.rule_conditions_explain(rule, day_pv.get(rule.get("cond_sun_day") or "today"),
                                         soc_now, spot_kwh, spot_latched=latched, soc_latched=soc_latched)
        would = bool(rule.get("enabled")) and win_ok and ev["ok"]
        item = {"id": rule["id"], "label": rule.get("label") or rule["action"], "action": rule["action"],
                "target": rule.get("target"), "power_kw": rule.get("power_kw"),
                "enabled": bool(rule.get("enabled")), "days": rule.get("days") or "1234567",
                "window": f"{rule.get('time_from')}–{rule.get('time_to')}",
                "day_ok": day_ok, "window_ok": win_ok,
                "conditions": ev["conditions"], "formula": ev["formula"], "logic": ev["logic"],
                "conditions_ok": ev["ok"], "would_run": would}
        if would and rule["action"] in ("force_charge", "force_discharge", "stop") and winner_batt is None:
            winner_batt = rule["id"]
        out.append(item)
    for it in out:
        if it["action"] in ("force_charge", "force_discharge", "stop") and it["would_run"]:
            it["note"] = "▶ TOTO pravidlo teď řídí baterii" if it["id"] == winner_batt else "aktivní, ale přebito dřívějším pravidlem"
    return {"now": now.isoformat(), "inputs": {"soc_pct": soc_now, "spot_czk_kwh": spot_kwh,
                                             "pv_today_kwh": day_pv.get("today"), "pv_tomorrow_kwh": day_pv.get("tomorrow")},
            "holder": holder, "rules": out}


@router.post("/{locality_id}/time-rules")
async def create_time_rule(locality_id: int, body: TimeRuleIn,
                           _: dict = Depends(require_permission("control"))):
    return await pdb.create_time_rule(locality_id, _validate_rule(body, require_all=True))


@router.put("/{locality_id}/time-rules/{rid}")
async def update_time_rule(locality_id: int, rid: int, body: TimeRuleIn,
                           _: dict = Depends(require_permission("control"))):
    out = await pdb.update_time_rule(locality_id, rid, _validate_rule(body, require_all=False))
    if not out:
        raise HTTPException(status_code=404, detail="Pravidlo nenalezeno")
    return out


@router.delete("/{locality_id}/time-rules/{rid}")
async def delete_time_rule(locality_id: int, rid: int,
                           _: dict = Depends(require_permission("control"))):
    if not await pdb.delete_time_rule(locality_id, rid):
        raise HTTPException(status_code=404, detail="Pravidlo nenalezeno")
    return {"ok": True}
