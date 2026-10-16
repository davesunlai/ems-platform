"""🔬 Diagnostické veličiny s omezenou dobou ukládání (v0.94.0).

MPPT napětí/proud/výkon ze Solisu se čtou ZDARMA (jsou v už načteném bloku 33029–33058),
adaptér je posílá vždy. Do DB se ukládají jen dokud platí params.mppt_diag_until modulu
(ISO čas), aby diagnostika neplnila databázi natrvalo. Starší než DIAG_KEEP_DAYS se mažou.
"""
from __future__ import annotations

from datetime import datetime, timezone

DIAG_METRICS = frozenset(
    f"pv_{k}_{i}" for i in (1, 2, 3, 4) for k in ("voltage", "current", "power"))
DIAG_KEEP_DAYS = 30


def diag_until(params: dict | None) -> datetime | None:
    raw = (params or {}).get("mppt_diag_until")
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def diag_active(params: dict | None) -> bool:
    u = diag_until(params)
    return bool(u and u > datetime.now(timezone.utc))


# Pomalé veličiny: čtou se každý cyklus, ale do DB jdou nejvýš 1× za SLOW_INTERVAL_S
# (BMS články, energetické čítače) — mění se pomalu, 10s vzorkování by jen plnilo DB.
SLOW_METRICS = frozenset(
    [f"battery_{k}_{n}" for n in (1, 2) for k in ("cell_vmin", "cell_vmax", "cell_tmin", "cell_tmax", "cell_nmin",
                                                   "cell_nmax", "bms_current", "cycles", "bms_modules", "bms_cells_per_module")]
    + [f"energy_{k}_{p}" for k in ("bat_charge", "bat_discharge", "import", "export", "load") for p in ("today", "total")])
SLOW_INTERVAL_S = 60
_last_slow: dict[tuple[str, str], float] = {}


def keep_metric(metric: str, params: dict | None, device_id: str | None = None, ts: datetime | None = None) -> bool:
    """False = neukládat: diagnostická veličina mimo aktivní okno, nebo pomalá veličina
    dřív než SLOW_INTERVAL_S po posledním uloženém vzorku téhož zařízení."""
    if metric in DIAG_METRICS and not diag_active(params):
        return False
    if metric in SLOW_METRICS:
        t = (ts or datetime.now(timezone.utc)).timestamp()
        key = (device_id or "", metric)
        last = _last_slow.get(key)
        if last is not None and 0 <= t - last < SLOW_INTERVAL_S:
            return False
        _last_slow[key] = t
    return True
