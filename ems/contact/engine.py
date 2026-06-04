"""Hystereze spínání kontaktu dle SOC.

Sepnout na horní mezi (SOC ≥ upper), rozepnout na dolní (SOC ≤ lower).
Stav (contact_on) se drží v DB → žádné poskakování, edge-trigger.
"""
from __future__ import annotations

import logging

from ems.control import db as control_db
from ems.control.goodwe_control import set_load_switch
from ems.modules import db as modules_db
from . import db as contact_db

logger = logging.getLogger("ems.contact")


async def _latest_soc(device_id: str):
    from ems.api.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM samples WHERE device_id=$1 AND metric='battery_soc' "
            "AND time > now() - interval '10 minutes' ORDER BY time DESC LIMIT 1",
            device_id,
        )
    return float(row["value"]) if row else None


async def evaluate_contacts() -> None:
    for c in await contact_db.list_all():
        if not c["enabled"]:
            continue
        dev = c["device_id"]
        soc = await _latest_soc(dev)
        if soc is None:
            await contact_db.set_decision(dev, "no_data:soc")
            continue

        upper, lower, on_now = c["upper_soc"], c["lower_soc"], c["contact_on"]
        desired = on_now
        if not on_now and soc >= upper:
            desired = True
        elif on_now and soc <= lower:
            desired = False

        if desired == on_now:
            await contact_db.set_decision(
                dev, f"SoC={soc:.0f} % (mez {lower}–{upper}); kontakt {'sepnut' if on_now else 'rozepnut'}")
            continue

        mod = await modules_db.get(dev)
        if not mod or mod.adapter != "goodwe" or not mod.params.get("host"):
            continue
        host = mod.params["host"]; port = int(mod.params.get("port", 8899))
        try:
            res = await set_load_switch(host, port, desired)
            await contact_db.set_state(
                dev, desired, f"SoC={soc:.0f} % → {'sepnuto' if desired else 'rozepnuto'}")
            await control_db.record(
                "contact:auto", dev, "load-switch",
                {"on": desired, "soc": soc, "upper": upper, "lower": lower}, True, res)
            logger.info("Kontakt [%s] → %s (SoC=%.0f)", dev, "ON" if desired else "OFF", soc)
        except Exception as exc:
            await control_db.record(
                "contact:auto", dev, "load-switch", {"on": desired}, False, {"error": str(exc)})
            logger.warning("Kontakt [%s] přepnutí selhalo: %s", dev, exc)
