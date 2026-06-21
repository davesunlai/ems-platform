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


def sum_series(series_list: list[list[dict]]) -> list[dict]:
    """Sečte výrobu více bloků po stejných časech (ts)."""
    acc: dict = {}
    for series in series_list:
        for r in series:
            acc[r["ts"]] = acc.get(r["ts"], 0.0) + r["pv_w"]
    return [{"ts": ts, "pv_w": acc[ts]} for ts in sorted(acc)]
