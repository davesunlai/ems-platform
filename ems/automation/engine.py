"""Automatizační engine: vyhodnocuje pravidla a edge-triggerem řídí.

Bezpečnostní vlastnosti:
- Povel se pošle jen když SKUTEČNÝ režim měniče neodpovídá záměru
  (čte se z device_state) — žádné spamování, samoopravné i po ruční změně.
- Minimální interval mezi povely jednoho pravidla (anti-flapping).
- Každý automatický povel jde do auditu jako 'automation:<rule>'.
"""
from __future__ import annotations

import logging
import time

from ems.api.db import get_pool
from ems.control import db as control_db
from ems.control.goodwe_control import set_battery_mode
from ems.modules import db as modules_db
from . import db as auto_db

logger = logging.getLogger("ems.automation")

CHARGE_MODES = {"ECO_CHARGE", "ECO"}
NORMAL_MODES = {"GENERAL", "SELF_USE"}
MIN_CMD_INTERVAL = 60.0
_last_cmd: dict[str, float] = {}


async def _latest_soc(device_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT value FROM samples WHERE device_id=$1 AND metric='battery_soc' "
            "AND time > now() - interval '5 minutes' ORDER BY time DESC LIMIT 1",
            device_id,
        )


async def _set_automation_state(device_id: str, value) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if value is None:
            await conn.execute(
                "DELETE FROM device_state WHERE device_id=$1 AND key='automation'", device_id
            )
        else:
            await conn.execute(
                "INSERT INTO device_state (device_id, key, value, updated_at) "
                "VALUES ($1, 'automation', $2, now()) "
                "ON CONFLICT (device_id, key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()",
                device_id, value,
            )


async def _actual_mode(device_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT value FROM device_state WHERE device_id=$1 AND key='operation_mode' "
            "AND updated_at > now() - interval '5 minutes'",
            device_id,
        )


async def evaluate_all(price) -> None:
    for r in await auto_db.list_enabled():
        try:
            await _eval_rule(r, price)
        except Exception as exc:
            logger.warning("Vyhodnocení pravidla '%s' selhalo: %s", r.id, exc)


async def _eval_rule(r, price) -> None:
    if r.type != "spot_charge":
        return
    p = r.params
    target = p.get("target_module")
    threshold = p.get("price_threshold")
    soc_max = float(p.get("soc_max", 95))
    charge_power = int(p.get("charge_power", 100))
    if not target or threshold is None or price is None:
        await auto_db.mark_eval(r.id, "no_data:price"); return
    threshold = float(threshold)

    soc = await _latest_soc(target)
    if soc is None:
        await auto_db.mark_eval(r.id, "no_data:soc"); return

    want_charge = (price < threshold) and (soc < soc_max)
    desired = "force_charge" if want_charge else "normal"
    await auto_db.mark_eval(
        r.id, f"{desired} (cena={price:.0f} práh={threshold:.0f} SoC={soc:.0f}/{soc_max:.0f})"
    )
    # stav pro dashboard: kdo a co řídí
    await _set_automation_state(target, r.id if desired == "force_charge" else None)

    actual = await _actual_mode(target)
    satisfied = (
        (desired == "force_charge" and actual in CHARGE_MODES)
        or (desired == "normal" and (actual in NORMAL_MODES or actual is None))
    )
    if satisfied:
        return

    now = time.monotonic()
    if now - _last_cmd.get(r.id, 0.0) < MIN_CMD_INTERVAL:
        return

    mod = await modules_db.get(target)
    if not mod or mod.adapter != "goodwe" or not mod.params.get("host"):
        await auto_db.mark_eval(r.id, "error:cíl není řiditelný"); return

    host = mod.params["host"]; port = int(mod.params.get("port", 8899))
    try:
        res = await set_battery_mode(host, port, desired, charge_power, int(soc_max))
        _last_cmd[r.id] = now
        await auto_db.mark_action(r.id, desired)
        await control_db.record(
            f"automation:{r.id}", target, "battery-mode",
            {"mode": desired, "power_pct": charge_power, "target_soc": int(soc_max)},
            True, {"requested": res["requested"], "confirmed": res.get("confirmed")},
        )
        logger.info("Automatizace '%s' → %s (cena=%.0f, SoC=%.0f)", r.id, desired, price, soc)
    except Exception as exc:
        await control_db.record(
            f"automation:{r.id}", target, "battery-mode", {"mode": desired}, False, {"error": str(exc)}
        )
        logger.warning("Automatizace '%s': povel selhal: %s", r.id, exc)
