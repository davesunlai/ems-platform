"""Vykonání povelu přes adaptér — SDÍLENÉ mezi serverovým kolektorem a EMSBOX
agentem (žádné DB závislosti; adaptér drží jediné Modbus spojení)."""
from __future__ import annotations


async def dispatch_command(adapter, action: str, params: dict) -> dict:
    p = params or {}
    if action == "force_charge":
        return await adapter.set_force(1, p.get("power"))
    if action == "force_discharge":
        return await adapter.set_force(2, p.get("power"))
    if action == "stop":
        return await adapter.set_force(0)
    if action == "force_poke":
        return await adapter.poke_force(int(p["mode"]))
    if action == "set_work_mode":
        return await adapter.set_work_mode(int(p["word"]))
    if action == "set_charge_current":
        return await adapter.set_charge_current(float(p["amps"]))
    if action == "set_discharge_current":
        return await adapter.set_discharge_current(float(p["amps"]))
    if action == "set_soc_backup":
        return await adapter.set_soc_backup(float(p["pct"]))
    if action == "set_soc_force":
        return await adapter.set_soc_force(float(p["pct"]))
    if action == "read_controls":
        return {"controls": await adapter.read_controls()}
    if action == "write_holding":
        return await adapter.write_holding(int(p["addr"]), int(p["value"]))
    if action == "read_holding":
        regs = await adapter.read_holding(int(p["addr"]), int(p.get("count", 1)))
        return {"addr": int(p["addr"]), "values": regs}
    raise ValueError(f"neznámý povel '{action}'")
