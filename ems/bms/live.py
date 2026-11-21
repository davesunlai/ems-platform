"""Živé sledování článků BMS: dokud má někdo otevřené okno s články, EMSBOX je čte à LIVE_S sekund.
Stav je jen v paměti API procesu (žádný zápis do DB); boxu se předává v nastavení konfigurace (settings.live)."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

LIVE_S = 5            # perioda čtení na boxu při živém sledování
HOLD_S = 60           # jak dlouho po posledním „pingu“ z UI živé čtení trvá
_until: dict[str, datetime] = {}
_latest: dict[str, tuple[datetime, dict]] = {}
TREND_N = 60          # trend článku = změna napětí přes posledních TREND_N snímků (živě ≈ 5 min, jinak ≈ 1 h)
_hist: dict[str, deque] = {}


def touch(module_id: str) -> datetime:
    """UI hlásí, že okno je otevřené. Prodlužuje se až když zbývá < polovina (ať se konfigurace boxu nemění každým pingem)."""
    now = datetime.now(timezone.utc)
    cur = _until.get(module_id)
    if cur is None or (cur - now).total_seconds() < HOLD_S / 2:
        _until[module_id] = now + timedelta(seconds=HOLD_S)
    return _until[module_id]


def active() -> dict[str, str]:
    now = datetime.now(timezone.utc)
    for k in [k for k, v in _until.items() if v <= now]:
        _until.pop(k, None)
    return {k: v.isoformat() for k, v in sorted(_until.items())}


def put(device_id: str, ts: datetime, arrays: dict) -> dict:
    """Uloží poslední stav; živé snímky nesou jen napětí → teploty se převezmou z posledního úplného čtení."""
    prev = _latest.get(device_id)
    if prev is not None and ts < prev[0]:
        return prev[1]                              # starší dávka (dosílání z bufferu) nepřepíše novější stav
    merged = {**(prev[1] if prev else {}), **arrays}
    _latest[device_id] = (ts, merged)
    if arrays.get("bms_cells_mv"):
        _hist.setdefault(device_id, deque(maxlen=TREND_N)).append((ts, list(arrays["bms_cells_mv"])))
    return merged


def seed(device_id: str, arrays: dict) -> dict:
    """Doplní do posledního stavu chybějící pole (teploty po restartu serveru); existující hodnoty nepřepisuje."""
    prev = _latest.get(device_id)
    if prev is None:
        return arrays
    merged = {**arrays, **prev[1]}
    _latest[device_id] = (prev[0], merged)
    return merged


def trend(device_id: str) -> dict | None:
    """Rychlost změny napětí každého článku v mV/min z posledních až TREND_N snímků
    (průměr 3 nejnovějších − průměr 3 nejstarších, děleno časem mezi nimi — tlumí kvantizační šum ±1 mV)."""
    h = list(_hist.get(device_id) or [])
    if len(h) < 4:
        return None
    k = 3 if len(h) >= 8 else 1
    old, new = h[:k], h[-k:]
    n = min(len(x[1]) for x in old + new)
    t_old = sum(x[0].timestamp() for x in old) / k
    t_new = sum(x[0].timestamp() for x in new) / k
    dt_min = (t_new - t_old) / 60.0
    if dt_min <= 0.05:
        return None
    rate = [round((sum(x[1][i] for x in new) / k - sum(x[1][i] for x in old) / k) / dt_min, 2) for i in range(n)]
    return {"rate": rate, "samples": len(h), "window_s": round(h[-1][0].timestamp() - h[0][0].timestamp()),
            "max_up": max([r for r in rate if r > 0], default=0.0), "max_down": min([r for r in rate if r < 0], default=0.0)}


def latest(device_id: str) -> tuple[datetime, dict] | None:
    return _latest.get(device_id)
