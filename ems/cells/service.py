"""Denní kontrola nerovnováhy článků: za 24 h najde největší (Umax − Umin) při SoC < X a při SoC > Y;
překročení prahu → operační událost kind 'cells' (→ výstrahy + e-mail uživatelům lokality s notifikacemi)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ems.localities import db as loc_db
from . import db

logger = logging.getLogger("ems.cells")


async def _solis_modules(locality_id: int) -> list[str]:
    from ems.api.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM modules WHERE locality_id = $1 AND adapter = 'solis' ORDER BY id", locality_id)
    return [r["id"] for r in rows]


def _cell_txt(n, cpm) -> str:
    """'162 (modul 11, poz. 12)' — číslo článku s modulem/pozicí (cpm = článků na modul)."""
    if n is None:
        return "?"
    n = int(round(n))
    if cpm and cpm > 0:
        cpm = int(round(cpm))
        return f"{n} (modul {(n - 1) // cpm + 1}, poz. {(n - 1) % cpm + 1})"
    return str(n)


def _local_hm(t: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo("Europe/Prague")).strftime("%d.%m. %H:%M")
    except Exception:
        return t.strftime("%H:%M UTC")


def _worst(series: list[dict], pred) -> dict | None:
    best = None
    for p in series:
        if not pred(p["soc"]):
            continue
        d = (p["vmax"] - p["vmin"]) * 1000.0
        if best is None or d > best["delta_mv"]:
            cpm = p.get("cpm")
            best = {"delta_mv": round(d, 0), "soc": round(p["soc"], 1), "vmin": round(p["vmin"], 3),
                    "vmax": round(p["vmax"], 3), "t": p["t"].isoformat(), "t_local": _local_hm(p["t"]),
                    "nmin": int(round(p["nmin"])) if p.get("nmin") is not None else None,
                    "nmax": int(round(p["nmax"])) if p.get("nmax") is not None else None,
                    "nmin_txt": _cell_txt(p.get("nmin"), cpm), "nmax_txt": _cell_txt(p.get("nmax"), cpm)}
    return best


async def check_locality(locality_id: int, cfg: dict | None = None, notify: bool = True) -> dict:
    cfg = cfg or await db.get_config(locality_id)
    out = {"checked_at": datetime.now(timezone.utc).isoformat(), "packs": [], "alerts": []}
    for dev in await _solis_modules(locality_id):
        for pack in (1, 2):
            series = await db.pack_series(dev, pack, 24)
            if not series:
                continue
            low = _worst(series, lambda s: s < float(cfg["soc_low"]))
            high = _worst(series, lambda s: s > float(cfg["soc_high"]))
            overall = _worst(series, lambda s: True)
            rec = {"device": dev, "pack": pack, "samples": len(series), "low": low, "high": high, "overall": overall}
            if low and low["delta_mv"] > float(cfg["delta_low_mv"]):
                rec["alert_low"] = True
                out["alerts"].append(
                    f"Baterie {pack}: při SoC {low['soc']:.0f} % (< {cfg['soc_low']:g} %) rozptyl článků "
                    f"{low['delta_mv']:.0f} mV > {cfg['delta_low_mv']:g} mV — nejnižší článek {low['nmin_txt']} {low['vmin']:.3f} V, "
                    f"nejvyšší článek {low['nmax_txt']} {low['vmax']:.3f} V ({low['t_local']})")
            if high and high["delta_mv"] > float(cfg["delta_high_mv"]):
                rec["alert_high"] = True
                out["alerts"].append(
                    f"Baterie {pack}: při SoC {high['soc']:.0f} % (> {cfg['soc_high']:g} %) rozptyl článků "
                    f"{high['delta_mv']:.0f} mV > {cfg['delta_high_mv']:g} mV — nejnižší článek {high['nmin_txt']} {high['vmin']:.3f} V, "
                    f"nejvyšší článek {high['nmax_txt']} {high['vmax']:.3f} V ({high['t_local']})")
            out["packs"].append(rec)
    await db.save_result(locality_id, out)
    if out["alerts"] and notify:
        try:
            from ems.alerts import db as alerts_db
            loc = await loc_db.get(locality_id)
            await alerts_db.record_event(
                locality_id, "cells", f"Nerovnováha článků baterie – {(loc or {}).get('name', locality_id)}",
                "Denní kontrola za posledních 24 h:\n" + "\n".join("• " + a for a in out["alerts"])
                + "\n\nDoporučení: sledovat trend v bloku 🔋 Články; při opakování kontaktovat servis baterie (balancování / vadný článek).")
        except Exception as exc:
            logger.warning("cells record_event: %s", exc)
    logger.info("cells check lok %s: %d packů, %d upozornění", locality_id, len(out["packs"]), len(out["alerts"]))
    return out


async def tick(state: dict) -> None:
    """Jednou za hodinu: pro zapnuté lokality spustí kontrolu, pokud od poslední uběhlo ≥ 23 h
    a lokální hodina ≥ check_hour."""
    import time as _t
    now = _t.monotonic()
    if now - state.get("_cells_tick", 0) < 3600:
        return
    state["_cells_tick"] = now
    try:
        from zoneinfo import ZoneInfo
        local_hour = datetime.now(ZoneInfo("Europe/Prague")).hour
        for cfg in await db.enabled_localities():
            last = cfg.get("last_check_at")
            due = last is None or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() >= 23 * 3600
            if due and local_hour >= int(cfg.get("check_hour") or 6):
                await check_locality(cfg["locality_id"], cfg)
    except Exception as exc:
        logger.debug("cells tick: %s", exc)
