"""Živé sledování článků BMS: dokud má někdo otevřené okno s články, EMSBOX je čte à LIVE_S sekund.
Stav je jen v paměti API procesu (žádný zápis do DB); boxu se předává v nastavení konfigurace (settings.live)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

LIVE_S = 5            # perioda čtení na boxu při živém sledování
HOLD_S = 60           # jak dlouho po posledním „pingu“ z UI živé čtení trvá
_until: dict[str, datetime] = {}
_latest: dict[str, tuple[datetime, dict]] = {}


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
    return merged


def latest(device_id: str) -> tuple[datetime, dict] | None:
    return _latest.get(device_id)
