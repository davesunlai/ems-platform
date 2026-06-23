"""Endpoint agregovaných výstrah."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ems.auth.deps import require_permission
from . import service
from . import db as alerts_db

router = APIRouter(tags=["alerts"])


@router.get("/api/alerts")
async def list_alerts(user: dict = Depends(require_permission("read"))):
    alerts = await service.collect_for_user(user)
    from ems.localities import db as loc_db
    try:
        browser_locs = await loc_db.browser_localities_for_user(user["id"])
    except Exception:
        browser_locs = []
    return {"count": len(alerts), "alerts": alerts, "browser_localities": browser_locs}


@router.post("/api/alerts/test")
async def test_notification(user: dict = Depends(require_permission("read"))):
    """Vyrobí okamžitou testovací událost ve viditelných lokalitách uživatele
    (projeví se v zvonečku, browser notifikaci i e-mailu opt-in uživatelům)."""
    localities = await service._visible_localities(user)
    for loc in localities:
        await alerts_db.record_event(loc["id"], "test", "Testovací notifikace",
                                     f"Ručně spuštěno ({user.get('username')})")
    # rozešli hned (jinak by e-mail čekal na 5min tick kolektoru)
    try:
        from ems.notify import dispatch as notify_dispatch
        await notify_dispatch.notify_new_alerts()
    except Exception:
        pass
    return {"ok": True, "localities": len(localities)}
