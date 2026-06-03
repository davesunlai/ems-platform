"""Zápis povelů do Goodwe ET měniče + ověření čtením.

Bezpečnost: krátkodobé připojení (connect → set → read-back → close).
Po zápisu se přečte aktuální režim a vrátí se pro audit i UI.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("ems.control")


async def set_battery_mode(host: str, port: int, mode: str,
                           power_pct: int = 100, target_soc: int = 100) -> dict:
    import goodwe
    from goodwe.inverter import OperationMode

    inverter = await goodwe.connect(host, port=port)

    if mode == "force_charge":
        await inverter.set_operation_mode(
            OperationMode.ECO_CHARGE, eco_mode_power=power_pct, eco_mode_soc=target_soc
        )
        requested = "ECO_CHARGE"
    elif mode == "force_discharge":
        # ECO_DISCHARGE: vybíjí baterii (do sítě) až na spodní SoC (target_soc = podlaha)
        await inverter.set_operation_mode(
            OperationMode.ECO_DISCHARGE, eco_mode_power=power_pct, eco_mode_soc=target_soc
        )
        requested = "ECO_DISCHARGE"
    elif mode == "normal":
        await inverter.set_operation_mode(OperationMode.GENERAL)
        requested = "GENERAL"
    else:
        raise ValueError(f"Neznámý režim '{mode}'")

    # read-back ověření
    confirmed = None
    try:
        cm = await inverter.get_operation_mode()
        confirmed = cm.name if cm is not None else None
    except Exception as exc:
        logger.warning("Read-back režimu selhal: %s", exc)

    return {"requested": requested, "confirmed": confirmed}


async def read_battery_mode(host: str, port: int) -> str | None:
    import goodwe
    inverter = await goodwe.connect(host, port=port)
    cm = await inverter.get_operation_mode()
    return cm.name if cm is not None else None
