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
DISCHARGE_MODES = {"ECO_DISCHARGE"}
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


async def evaluate_all(price, skip_devices=None) -> None:
    """Vyhodnotí všechna pravidla, agregovaně podle cílového zařízení.

    `skip_devices` — moduly řízené plánovačem; reaktivní pravidla je přeskočí,
    aby si dva regulátory nelezly do zelí (plánovač má přednost).
    """
    skip = set(skip_devices or [])
    by_target: dict[str, list] = {}
    for r in await auto_db.list_enabled():
        t = r.params.get("target_module")
        if t and t not in skip:
            by_target.setdefault(t, []).append(r)
    for target, rules in by_target.items():
        try:
            await _eval_device(target, rules, price)
        except Exception as exc:
            logger.warning("Vyhodnocení zařízení '%s' selhalo: %s", target, exc)


async def _eval_device(target: str, rules: list, price) -> None:
    soc = await _latest_soc(target)
    actual = await _actual_mode(target)
    charging_now = actual in CHARGE_MODES

    # 1) spočítej rozhodnutí každého pravidla (pro UI) a najdi aktivní kandidáty
    charge_rule = None
    discharge_rule = None
    for r in rules:
        p = r.params
        if price is None or soc is None:
            await auto_db.mark_eval(r.id, "no_data")
            continue
        if r.type == "spot_charge":
            thr = float(p.get("price_threshold", 0)); smax = float(p.get("soc_max", 95))
            sstart = float(p.get("soc_start", smax))   # začni nabíjet jen pod tímto SoC
            # hystereze: spustí se až pod sstart, nabíjí dál až po smax (drží přes skutečný režim)
            on = price < thr and soc < smax and (charging_now or soc <= sstart)
            await auto_db.mark_eval(
                r.id, f"{'force_charge' if on else 'normal'} (cena={price:.0f} práh<{thr:.0f} SoC={soc:.0f} start≤{sstart:.0f} stop≥{smax:.0f})"
            )
            if on and charge_rule is None:
                charge_rule = r
        elif r.type == "spot_discharge":
            thr = float(p.get("price_threshold", 0)); smin = float(p.get("soc_min", 20))
            on = price > thr and soc > smin
            await auto_db.mark_eval(
                r.id, f"{'force_discharge' if on else 'normal'} (cena={price:.0f} práh>{thr:.0f} SoC={soc:.0f}/{smin:.0f})"
            )
            if on and discharge_rule is None:
                discharge_rule = r

    if price is None or soc is None:
        return

    # 2) výsledný záměr pro zařízení (nabíjení má přednost; normálně se nepřekrývají)
    if charge_rule is not None:
        desired, chosen = "force_charge", charge_rule
        power = int(chosen.params.get("charge_power", 100))
        soc_arg = int(chosen.params.get("soc_max", 95))
    elif discharge_rule is not None:
        desired, chosen = "force_discharge", discharge_rule
        power = int(chosen.params.get("discharge_power", 100))
        soc_arg = int(chosen.params.get("soc_min", 20))
    else:
        desired, chosen, power, soc_arg = "normal", None, 100, 100

    # 3) indikátor pro dashboard
    await _set_automation_state(target, chosen.id if chosen else None)

    # 4) edge-trigger podle skutečného režimu
    satisfied = (
        (desired == "force_charge" and actual in CHARGE_MODES)
        or (desired == "force_discharge" and actual in DISCHARGE_MODES)
        or (desired == "normal" and (actual in NORMAL_MODES or actual is None))
    )
    if satisfied:
        return

    now = time.monotonic()
    if now - _last_cmd.get(target, 0.0) < MIN_CMD_INTERVAL:
        return

    mod = await modules_db.get(target)
    if not mod or mod.adapter != "goodwe" or not mod.params.get("host"):
        return

    host = mod.params["host"]; port = int(mod.params.get("port", 8899))
    actor = chosen.id if chosen else "auto-normal"
    try:
        res = await set_battery_mode(host, port, desired, power, soc_arg)
        _last_cmd[target] = now
        if chosen is not None:
            await auto_db.mark_action(chosen.id, desired)
        else:
            for r in rules:
                await auto_db.mark_action(r.id, "normal")
        await control_db.record(
            f"automation:{actor}", target, "battery-mode",
            {"mode": desired, "power_pct": power, "target_soc": soc_arg},
            True, {"requested": res["requested"], "confirmed": res.get("confirmed")},
        )
        logger.info("Automatizace [%s] → %s (cena=%.0f, SoC=%.0f)", target, desired, price, soc)
    except Exception as exc:
        await control_db.record(
            f"automation:{actor}", target, "battery-mode", {"mode": desired}, False, {"error": str(exc)}
        )
        logger.warning("Automatizace [%s]: povel '%s' selhal: %s", target, desired, exc)
