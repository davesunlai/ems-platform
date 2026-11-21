"""BMS po RS485: poslední stav všech článků bloků lokality."""
from __future__ import annotations

import statistics

from fastapi import APIRouter, Depends

from ems.auth.deps import require_permission
from . import db, live

router = APIRouter(prefix="/api/bms", tags=["bms"])
read = require_permission("read")

SUMMARY = ["bms_voltage", "bms_current", "bms_soc", "bms_cell_vmax", "bms_cell_vmin", "bms_cell_nmax", "bms_cell_nmin",
           "bms_cell_delta_mv", "bms_temp_max", "bms_temp_min"]


@router.get("/{locality_id}")
async def bms_locality(locality_id: int, _: dict = Depends(read)) -> list[dict]:
    """Pro každý BMS modul lokality: souhrn + napětí/teploty všech článků po modulech + odchylky od mediánu."""
    from ems.localities import db as loc_db
    from ems.api.db import list_devices
    from ems.battest import db as bt_db
    from ems.modules import db as modules_db
    devs = {d["device_id"]: d for d in await list_devices()}
    out = []
    for d in await loc_db.devices_for_locality(locality_id):
        if (devs.get(d["id"]) or {}).get("adapter") != "pylontech_sc0500":
            continue
        mod = await modules_db.get(d["id"])
        params = (getattr(mod, "params", None) or {}) if mod is not None else {}
        cells = await db.latest(d["id"])
        lv = live.latest(d["id"])
        is_live = False
        if lv and (cells is None or lv[0].isoformat() > cells["time"]):
            ints = lambda k: [int(round(x)) for x in (lv[1].get(k) or [])]
            cells = {"time": lv[0].isoformat(), "mv": ints("bms_cells_mv"), "temp": ints("bms_cells_temp"),
                     "module_cv": ints("bms_modules_cv"), "module_temp": ints("bms_modules_temp")}
            is_live = True
        item = {"module_id": d["id"], "name": getattr(mod, "name", None) or d["id"], "block_idx": params.get("block_idx"),
                "summary": await bt_db.latest_metrics(d["id"], SUMMARY, 600), "cells": None}
        if cells and cells["mv"]:
            mv = cells["mv"]
            n_mod = len(cells["module_cv"]) or 1
            per = max(1, len(mv) // n_mod)
            med = statistics.median(mv)
            mods = []
            for i in range(0, len(mv), per):
                chunk = mv[i:i + per]
                mods.append({"idx": i // per + 1, "mv": chunk, "avg": round(sum(chunk) / len(chunk), 1),
                             "min": min(chunk), "max": max(chunk),
                             "temp": (cells["temp"][i:i + per] if cells["temp"] else []),
                             "voltage": (cells["module_cv"][i // per] / 100.0 if i // per < len(cells["module_cv"]) else None),
                             "temp_module": (cells["module_temp"][i // per] / 10.0 if i // per < len(cells["module_temp"]) else None)})
            from datetime import datetime, timezone
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(cells["time"])).total_seconds()
            item["live"] = {"active": d["id"] in live.active(), "from_memory": is_live, "age_s": round(age, 1), "period_s": live.LIVE_S}
            item["trend"] = live.trend(d["id"])
            item["cells"] = {"time": cells["time"], "count": len(mv), "per_module": per, "median": med,
                             "min": min(mv), "max": max(mv), "delta": max(mv) - min(mv),
                             "nmin": mv.index(min(mv)) + 1, "nmax": mv.index(max(mv)) + 1, "modules": mods}
        # výkon bloku: z měniče (battery_power_N, + nabíjení / − vybíjení, ověřené znaménko); jinak U×I z BMS (znaménko proudu neověřeno)
        try:
            idx = int(params.get("block_idx") or 0)
            pw = None
            for dd in await loc_db.devices_for_locality(locality_id):
                if idx and (devs.get(dd["id"]) or {}).get("adapter") == "solis":
                    pw = (await bt_db.latest_metrics(dd["id"], [f"battery_power_{idx}"], 180)).get(f"battery_power_{idx}")
                    if pw is not None:
                        break
            src = "měnič"
            if pw is None and item["summary"].get("bms_voltage") is not None and item["summary"].get("bms_current") is not None:
                pw, src = item["summary"]["bms_voltage"] * item["summary"]["bms_current"], "BMS"
            item["power"] = {"w": round(pw) if pw is not None else None, "source": src}
        except Exception:
            item["power"] = {"w": None, "source": None}
        out.append(item)
    return out


@router.post("/live/{module_id}")
async def bms_live(module_id: str, _: dict = Depends(read)) -> dict:
    """Okno s články je otevřené → EMSBOX čte články à LIVE_S s ještě HOLD_S sekund (UI volá opakovaně). Jen čtení z BMS."""
    until = live.touch(module_id)
    return {"module_id": module_id, "until": until.isoformat(), "period_s": live.LIVE_S}
