"""Agregátor výstrah pro přihlášeného uživatele.

Sbírá výstrahy napříč zdroji a scopuje je na lokality, které uživatel vidí
(admin = všechny, ostatní = přiřazené lokality). Navrženo tak, aby šlo
snadno přidat další typy výstrah (poruchy, překročení limitů, offline zařízení…).
"""
from __future__ import annotations

import datetime as dt

from ems.auth import db as auth_db
from ems.localities import db as loc_db
from ems.outages import db as outage_db


async def _visible_localities(user: dict) -> list[dict]:
    if "admin" in user.get("permissions", set()):
        return await loc_db.list_all()
    u = await auth_db.get_user(user.get("username") or "")
    if not u:
        return []
    return await loc_db.localities_for_user(u["id"])


def _fmt(start_iso: str, end_iso: str) -> str:
    s = dt.datetime.fromisoformat(start_iso)
    e = dt.datetime.fromisoformat(end_iso)
    return f"{s.strftime('%d.%m. %H:%M')}–{e.strftime('%H:%M')}"


async def _outage_alerts(localities: list[dict]) -> list[dict]:
    alerts: list[dict] = []
    for loc in localities:
        rows = await outage_db.list_for_locality(loc["id"], upcoming_only=True)
        for o in rows:
            detail = _fmt(o["start"], o["end"])
            if o.get("locations"):
                detail += " · " + o["locations"]
            alerts.append({
                "id": f"outage:{o['uid']}",
                "type": "outage",
                "severity": "warning",
                "locality_id": loc["id"],
                "locality_name": loc.get("name"),
                "title": "Plánovaná odstávka elektřiny",
                "detail": detail,
                "start": o["start"],
                "end": o["end"],
            })
    return alerts


async def collect_for_user(user: dict) -> list[dict]:
    localities = await _visible_localities(user)
    alerts: list[dict] = []
    alerts += await _outage_alerts(localities)
    # budoucí zdroje výstrah přidat sem
    alerts.sort(key=lambda a: a.get("start") or "")
    return alerts
