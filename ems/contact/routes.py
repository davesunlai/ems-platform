"""Endpointy pro SOC spínání kontaktu: konfigurace, stav, ruční test."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ems.auth.deps import require_permission
from ems.control import db as control_db
from ems.control.goodwe_control import set_load_switch
from ems.modules import db as modules_db
from . import db as contact_db
from .models import ContactSettings

router = APIRouter(prefix="/api/contact", tags=["contact"])


@router.get("")
async def list_contacts(_: dict = Depends(require_permission("read"))):
    return await contact_db.list_all()


@router.put("/{device_id}")
async def set_contact(device_id: str, body: ContactSettings,
                      _: dict = Depends(require_permission("control"))):
    patch = body.model_dump(exclude_unset=True)
    if "upper_soc" in patch and "lower_soc" in patch and patch["lower_soc"] >= patch["upper_soc"]:
        raise HTTPException(status_code=400, detail="Dolní mez musí být nižší než horní")
    return await contact_db.upsert(device_id, patch)


@router.post("/{device_id}/switch")
async def manual_switch(device_id: str, on: bool,
                        _: dict = Depends(require_permission("control"))):
    mod = await modules_db.get(device_id)
    if not mod or mod.adapter != "goodwe" or not mod.params.get("host"):
        raise HTTPException(status_code=400, detail="Zařízení není řiditelný Goodwe měnič")
    host = mod.params["host"]; port = int(mod.params.get("port", 8899))
    try:
        res = await set_load_switch(host, port, on)
    except Exception as exc:
        await control_db.record("contact:manual", device_id, "load-switch",
                                {"on": on}, False, {"error": str(exc)})
        raise HTTPException(status_code=502, detail=f"Přepnutí selhalo: {exc}")
    await contact_db.set_state(device_id, on, f"ruční {'sepnuto' if on else 'rozepnuto'}")
    await control_db.record("contact:manual", device_id, "load-switch", {"on": on}, True, res)
    return {"ok": True, "result": res}
