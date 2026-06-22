"""Výpočet reálné ceny import/export (CZK/kWh) z tarifu lokality.

SPOT:  import = (spot + přirážka + distribuce[VT/NT] + poplatky) / 1000
       export = (spot − provize_z_prodeje) / 1000
FIXED: import = fix_buy_[vt|nt];  export = fix_sell   (už v CZK/kWh)
"""
from __future__ import annotations

from datetime import datetime, timezone


def _nt_set(nt_hours: str | None) -> set[int]:
    if not nt_hours:
        return set()
    out = set()
    for part in str(nt_hours).split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def is_nt(tariff: dict, ts: datetime) -> bool:
    if not tariff.get("two_tariff"):
        return False
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("Europe/Prague")
    except Exception:
        tz = timezone.utc
    hour = ts.astimezone(tz).hour
    return hour in _nt_set(tariff.get("nt_hours"))


def price_czk_kwh(tariff: dict, ts: datetime, spot_czk_mwh: float | None) -> dict:
    """Vrátí {'import_czk', 'export_czk'} v CZK/kWh pro daný čas."""
    if not tariff:
        s = (spot_czk_mwh or 0) / 1000.0
        return {"import_czk": s, "export_czk": s}
    nt = is_nt(tariff, ts)
    if tariff.get("mode") == "fixed":
        imp = tariff.get("fix_buy_nt") if nt else tariff.get("fix_buy_vt")
        return {"import_czk": float(imp or 0), "export_czk": float(tariff.get("fix_sell") or 0)}
    # spot
    spot = spot_czk_mwh or 0.0
    dist = tariff.get("dist_buy_nt") if nt else tariff.get("dist_buy_vt")
    imp_mwh = spot + float(tariff.get("spot_buy_surcharge") or 0) + float(dist or 0) + float(tariff.get("levies") or 0)
    exp_mwh = spot - float(tariff.get("spot_sell_fee") or 0)
    return {"import_czk": imp_mwh / 1000.0, "export_czk": exp_mwh / 1000.0}
