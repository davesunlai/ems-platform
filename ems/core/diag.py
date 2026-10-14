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


def keep_metric(metric: str, params: dict | None) -> bool:
    """False = diagnostická veličina mimo aktivní okno → neukládat."""
    return metric not in DIAG_METRICS or diag_active(params)
