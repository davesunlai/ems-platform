"""PV model (Open-Meteo větev) — samokalibrující přes PR.

    P_ac        = kWp × (GTI/1000) × PR × temp_factor
    temp_factor = 1 − 0.004 × max(0, T_cell − 25)         # ~0.4 %/°C nad 25 °C
    T_cell      ≈ T_air + (NOCT−20)/800 × GTI             # zjednodušený NOCT model

Bifaciální panel přidá zadní zisk (placeholder faktor, doladí se kalibrací PR).
"""
from __future__ import annotations

MODEL_VERSION = "om-pv-1"
TEMP_COEFF = 0.004        # %/°C nad 25 °C
NOCT = 45.0
BIFACIAL_GAIN = 0.10      # +10 % (orientační; u plotu/agro může být vyšší)


def cell_temp(t_air: float | None, gti: float | None) -> float:
    if t_air is None:
        return 25.0
    g = gti or 0.0
    return t_air + (NOCT - 20.0) / 800.0 * g


def block_power_w(block_kwp: float, pr: float, panel_type: str, row: dict) -> float:
    """Okamžitý AC výkon bloku (W) z jednoho hodinového vzorku počasí."""
    gti = row.get("gti")
    if gti is None or gti <= 0:
        return 0.0
    tc = cell_temp(row.get("temp_c"), gti)
    temp_factor = 1.0 - TEMP_COEFF * max(0.0, tc - 25.0)
    gain = (1.0 + BIFACIAL_GAIN) if panel_type == "bifacial" else 1.0
    p_kw = block_kwp * (gti / 1000.0) * pr * temp_factor * gain
    return max(0.0, p_kw * 1000.0)


def block_series(block_kwp: float, pr: float, panel_type: str, weather: list[dict]) -> list[dict]:
    """Řada {ts, pv_w} pro jeden blok."""
    return [{"ts": r["ts"], "pv_w": block_power_w(block_kwp, pr, panel_type, r)} for r in weather]


DARK_SLOPE_DEFAULT = 0.5          # D' = max(D, slope·D + offset)  [kWh/den]
DARK_OFFSET_PER_KWP = 0.32        # auto offset = 0,32 kWh/kWp (pilot ~16 kWh); kalibrace 27. 10. 2026


def apply_dark_floor(series: list[dict], slope: float, offset_kwh: float, tz) -> tuple[list[dict], dict]:
    """Korekce Open-Meteo pro zatažené dny. OM při 100 % oblačnosti hlásí GHI ~20 W/m², reálná
    difuzní složka je 3–5× vyšší (3,6 → 18,1 kWh; 15,4 → 25,1; 24,9 → 36,8; nad ~32 kWh sedí).
    Denní součet D (lokální den) se zvedne na D' = max(D, slope·D + offset) a hodinová křivka se
    škáluje poměrem D'/D (tvar dne zůstává). Vrací (řada s pv_w_raw, {den: {raw, corr}})."""
    days: dict = {}
    for r in series:
        d = r["ts"].astimezone(tz).date()
        days[d] = days.get(d, 0.0) + r["pv_w"] / 1000.0
    factor, info = {}, {}
    for d, raw in days.items():
        corr = max(raw, slope * raw + offset_kwh) if raw > 0 else raw
        factor[d] = (corr / raw) if raw > 0 and corr > raw + 1e-6 else 1.0
        info[d.isoformat()] = {"raw_kwh": round(raw, 2), "corr_kwh": round(corr, 2)}
    out = [{"ts": r["ts"], "pv_w": r["pv_w"] * factor[r["ts"].astimezone(tz).date()], "pv_w_raw": r["pv_w"]}
           for r in series]
    return out, info


def sum_series(series_list: list[list[dict]]) -> list[dict]:
    """Sečte výrobu více bloků po stejných časech (ts)."""
    acc: dict = {}
    for series in series_list:
        for r in series:
            acc[r["ts"]] = acc.get(r["ts"], 0.0) + r["pv_w"]
    return [{"ts": ts, "pv_w": acc[ts]} for ts in sorted(acc)]
