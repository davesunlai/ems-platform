"""Endpoint pro zúčtovací období lokality (souhrn po měsících + součet)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from ems.localities import db as loc_db
from ems.pricing import db as pricing_db
from . import db as billing_db
from .period import current_period

router = APIRouter(tags=["billing"])


@router.get("/api/localities/{loc_id}/billing/days")
async def locality_billing_days(loc_id: int, month: str,
                                _: dict = Depends(require_permission("read"))):
    """Denní rozpad měsíce: kWh a Kč ze sítě / do sítě dle spotu a sazebníku
    platného V TOM ČASE (rate card valid_from → historická reprodukovatelnost)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from ems.pricing import cost as pricing_cost

    loc = await loc_db.get(loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    try:
        mstart = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="month musí být YYYY-MM")
    mend = (mstart.replace(day=28) + timedelta(days=4)).replace(day=1)

    devs = [d["id"] for d in await loc_db.devices_for_locality(loc_id)]
    rows = await billing_db.hourly_grid_spot(devs, mstart, mend)
    mode = loc.get("pricing_mode") or "spot"
    ti = float(loc.get("tariff_import_czk") or 0)
    te = float(loc.get("tariff_export_czk") or 0)

    tz = ZoneInfo("Europe/Prague")
    tariff_by_day: dict = {}
    days: dict[str, dict] = {}
    for r in rows:
        h = r["h"]
        local_day = h.astimezone(tz).date()
        key = local_day.isoformat()
        d = days.setdefault(key, {"day": key, "import_kwh": 0.0, "export_kwh": 0.0,
                                  "import_czk": 0.0, "export_czk": 0.0})
        np_kwh = float(r["np_kwh"] or 0.0)
        if mode == "tariff":
            pi, pe = ti, te
        else:
            t = tariff_by_day.get(key)
            if t is None and key not in tariff_by_day:
                t = await pricing_db.get_effective(loc_id, at=local_day)  # sazebník platný v ten den
                tariff_by_day[key] = t
            price = pricing_cost.price_czk_kwh(t, h, r["czk_mwh"])
            pi, pe = price["import_czk"], price["export_czk"]
        if np_kwh > 0:
            d["import_kwh"] += np_kwh
            d["import_czk"] += np_kwh * pi
        elif np_kwh < 0:
            d["export_kwh"] += -np_kwh
            d["export_czk"] += (-np_kwh) * pe

    out = []
    for key in sorted(days):
        d = days[key]
        out.append({"day": d["day"],
                    "import_kwh": round(d["import_kwh"], 1),
                    "export_kwh": round(d["export_kwh"], 1),
                    "import_czk": round(d["import_czk"], 2),
                    "export_czk": round(d["export_czk"], 2),
                    "saldo_czk": round(d["export_czk"] - d["import_czk"], 2)})
    return {"month": month, "days": out}


@router.get("/api/localities/{loc_id}/billing")
async def locality_billing(loc_id: int, _: dict = Depends(require_permission("read"))):
    loc = await loc_db.get(loc_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Lokalita nenalezena")
    settings = {
        "billing_start": loc.get("billing_start").isoformat() if loc.get("billing_start") else None,
        "billing_months": loc.get("billing_months") or 12,
        "export_limit_kwh": loc.get("export_limit_kwh"),
        "alert_enabled": bool(loc.get("alert_enabled")),
        "autolimit_enabled": bool(loc.get("autolimit_enabled")),
        "alert_email": loc.get("alert_email"),
        "pricing_mode": loc.get("pricing_mode") or "spot",
        "tariff_import_czk": loc.get("tariff_import_czk"),
        "tariff_export_czk": loc.get("tariff_export_czk"),
    }
    if not loc.get("billing_start"):
        return {"configured": False, "settings": settings}

    start, end = current_period(loc["billing_start"], settings["billing_months"], date.today())
    devs = [d["id"] for d in await loc_db.devices_for_locality(loc_id)]
    months = await billing_db.monthly_energy(devs, start, end)

    # Ceny ze sítě / do sítě. Primárně SAZEBNÍK lokality (locality_tariff) — stejný
    # cenový model jako plánovač: nákup = spot + přirážka + distribuce + poplatky,
    # prodej = spot − provize. Legacy pevný tarif (locality.pricing_mode='tariff')
    # zůstává jako override.
    mode = settings["pricing_mode"]
    tariff = await pricing_db.get_effective(loc_id)
    if mode == "tariff":
        ti = float(settings["tariff_import_czk"] or 0)
        te = float(settings["tariff_export_czk"] or 0)
        for r in months:
            r["import_czk"] = round(r["import_kwh"] * ti, 2)
            r["export_czk"] = round(r["export_kwh"] * te, 2)
    else:
        costs = await billing_db.monthly_cost(devs, tariff, start, end)
        for r in months:
            c = costs.get(r["month"], {})
            r["import_czk"] = round(c.get("import_czk", 0.0), 2)
            r["export_czk"] = round(c.get("export_czk", 0.0), 2)
    for r in months:
        r["saldo_czk"] = round(r.get("export_czk", 0) - r.get("import_czk", 0), 2)

    totals = {k: round(sum(r[k] for r in months), 1)
              for k in ("prod_kwh", "cons_kwh", "export_kwh", "import_kwh")}
    for k in ("import_czk", "export_czk", "saldo_czk"):
        totals[k] = round(sum(r.get(k, 0) for r in months), 2)

    # Paušály (měsíční fixní platby) — čistě účetní položka, do dispečinku nevstupuje.
    monthly_fee = float((tariff or {}).get("monthly_fee") or 0)
    fees_czk = round(monthly_fee * len(months), 2)
    settings["monthly_fee"] = monthly_fee
    settings["tariff_mode"] = (tariff or {}).get("mode")
    settings["spot_buy_surcharge"] = (tariff or {}).get("spot_buy_surcharge")
    settings["spot_sell_fee"] = (tariff or {}).get("spot_sell_fee")

    # Baseline (odběr/dodávka od začátku období do spuštění měření) — jen pro
    # aktuální období; po přechodu na další období se neuplatní.
    base_exp = base_imp = 0.0
    if loc.get("baseline_period_start") == start:
        base_exp = float(loc.get("baseline_export_kwh") or 0)
        base_imp = float(loc.get("baseline_import_kwh") or 0)
    totals["export_kwh"] = round(totals["export_kwh"] + base_exp, 1)
    totals["import_kwh"] = round(totals["import_kwh"] + base_imp, 1)

    return {
        "configured": True,
        "settings": settings,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "months": months,
        "baseline": {"export_kwh": round(base_exp, 1), "import_kwh": round(base_imp, 1)},
        "totals": totals,
        "fees_czk": fees_czk,
    }
