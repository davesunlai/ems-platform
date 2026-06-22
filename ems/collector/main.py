"""Kolektor: čte registr modulů z DB a periodicky pollovuje.

Spuštění:
    EMS_SINK=timescale python -m ems.collector.main

Reconciling smyčka: v každém cyklu načte aktivní čtecí moduly z DB a srovná
je s běžícími adaptéry — nové připojí, odebrané/vypnuté zavře. Díky tomu se
změny v admin UI (přidání/zapnutí/vypnutí modulu) projeví bez restartu.

Odolnost: chyba jednoho modulu (čtení i připojení) nezhodí celek; chyba DB
při načítání registru ponechá běžící adaptéry beze změny.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from ems.core.model import Device, reading_to_samples
from ems.modules import db as modules_db
from ems.market import db as market_db
from ems.market.spot import fetch_current_price_czk, fetch_day_slots
from ems.automation import db as automation_db
from ems.automation.engine import evaluate_all
from ems.control import db as control_db
from ems.forecast import db as forecast_db
from ems.forecast import service as forecast_service
from ems.pricing import db as pricing_db
from ems.pricing import fx as pricing_fx
from ems.outputs.engine import evaluate_outputs
from ems.outages.service import refresh_all as refresh_outages_all
from .config import build_adapter, build_sink

logging.basicConfig(
    level=os.getenv("EMS_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ems.collector")

POLL_INTERVAL = float(os.getenv("EMS_POLL_INTERVAL", "10"))
DEVICES_PATH = os.getenv("EMS_DEVICES", "devices.yaml")
MARKET_REFRESH = float(os.getenv("EMS_MARKET_REFRESH", "300"))  # s


def _module_to_device(m) -> Device:
    return Device(id=m.id, type=m.device_type, adapter=m.adapter, name=m.name,
                  region=m.region, params=m.params)


def _module_sig(m) -> str:
    """Podpis modulu pro detekci změny (adaptér + parametry, např. host/port)."""
    import json
    return json.dumps({"adapter": m.adapter, "params": m.params}, sort_keys=True, default=str)


async def poll_device(adapter, sink) -> None:
    try:
        reading = await adapter.read()
        await sink.write(reading_to_samples(reading))
        if reading.states and hasattr(sink, "write_states"):
            await sink.write_states(reading.device_id, reading.states)
    except Exception as exc:
        logger.warning("Čtení '%s' selhalo: %s", getattr(adapter, "device_id", "?"), exc)


async def dispatch_command(adapter, action: str, params: dict) -> dict:
    """Provede povel přes adaptér (drží jediné Modbus spojení). Vrací výsledek."""
    p = params or {}
    if action == "force_charge":
        return await adapter.set_force(1, p.get("power"))
    if action == "force_discharge":
        return await adapter.set_force(2, p.get("power"))
    if action == "stop":
        return await adapter.set_force(0)
    if action == "set_work_mode":
        return await adapter.set_work_mode(int(p["word"]))
    if action == "write_holding":
        return await adapter.write_holding(int(p["addr"]), int(p["value"]))
    if action == "read_holding":
        regs = await adapter.read_holding(int(p["addr"]), int(p.get("count", 1)))
        return {"addr": int(p["addr"]), "values": regs}
    raise ValueError(f"neznámý povel '{action}'")


async def process_queue(active: dict) -> None:
    """Vyřídí čekající povely pro aktivní moduly — SEKVENČNĚ v rámci cyklu,
    takže nekoliduje se čtením (jediné spojení na měnič)."""
    ids = list(active)
    if not ids:
        return
    try:
        cmds = await control_db.fetch_pending(ids)
    except Exception as exc:
        logger.debug("Načtení fronty povelů selhalo: %s", exc)
        return
    for c in cmds:
        adapter = (active.get(c["module_id"]) or {}).get("adapter")
        if adapter is None:
            continue
        try:
            res = await dispatch_command(adapter, c["action"], c["params"] or {})
            await control_db.complete(c["id"], True, res if isinstance(res, dict) else {"result": res})
            logger.info("Povel #%s '%s' (%s) OK: %s", c["id"], c["action"], c["module_id"], res)
        except Exception as exc:
            await control_db.complete(c["id"], False, {"error": str(exc)})
            logger.warning("Povel #%s '%s' (%s) selhal: %s", c["id"], c["action"], c["module_id"], exc)


async def _connect_module(m):
    adapter = build_adapter(_module_to_device(m))
    await adapter.connect()
    return adapter


async def reconcile(active: dict, sink) -> None:
    """Srovná běžící adaptéry s aktivními moduly v DB.

    active: {mid: {"adapter": <adaptér>, "sig": <podpis>}}
    Nové připojí, odebrané/vypnuté zavře a u existujících detekuje změnu
    parametrů (host/port/adaptér) -> zavře staré spojení a připojí znovu,
    takže změna IP v UI se projeví do jednoho cyklu (~POLL_INTERVAL).
    """
    try:
        wanted = await modules_db.list_enabled_reads()
    except Exception as exc:
        logger.warning("Načtení registru modulů selhalo, ponechávám stávající: %s", exc)
        return
    wanted_by_id = {m.id: m for m in wanted}

    # připoj nové + reconnectuj změněné
    for mid, m in wanted_by_id.items():
        sig = _module_sig(m)
        cur = active.get(mid)
        if cur is None:
            try:
                active[mid] = {"adapter": await _connect_module(m), "sig": sig}
                logger.info("Modul připojen: %s (adaptér=%s)", mid, m.adapter)
            except Exception as exc:
                logger.warning("Připojení modulu '%s' selhalo (zkusím příště): %s", mid, exc)
        elif cur["sig"] != sig:
            # parametry/adaptér se změnily -> zavři staré a připoj znovu
            try:
                await cur["adapter"].close()
            except Exception:
                pass
            try:
                active[mid] = {"adapter": await _connect_module(m), "sig": sig}
                logger.info("Modul přenastaven za běhu: %s (nové parametry)", mid)
            except Exception as exc:
                del active[mid]  # spadlo -> příští cyklus zkusí jako nový
                logger.warning("Reconnect modulu '%s' selhal (zkusím příště): %s", mid, exc)

    # odpoj odebrané/vypnuté
    for mid in list(active):
        if mid not in wanted_by_id:
            try:
                await active[mid]["adapter"].close()
            except Exception:
                pass
            del active[mid]
            logger.info("Modul odpojen: %s", mid)


async def run() -> None:
    # příprava registru + jednorázová migrace z devices.yaml
    try:
        await modules_db.ensure_schema()
        await modules_db.seed_from_devices(DEVICES_PATH)
        await market_db.ensure_schema()
        await market_db.ensure_history_schema()
        await automation_db.ensure_schema()
        await control_db.ensure_queue_schema()
        await forecast_db.ensure_schema()
        await pricing_db.ensure_schema()
    except Exception as exc:
        logger.error("Inicializace registru modulů selhala: %s", exc)

    sink = build_sink()
    active: dict = {}
    state = {"last_market": 0.0}

    stop = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Ukončuji…")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    logger.info("Kolektor běží (registr z DB), interval=%ss", POLL_INTERVAL)
    try:
        while not stop.is_set():
            await reconcile(active, sink)
            if active:
                await asyncio.gather(*(poll_device(e["adapter"], sink) for e in active.values()))
                await process_queue(active)
            await tick_market_and_automation(state)
            await tick_forecast(state)
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass
    finally:
        for e in active.values():
            try:
                await e["adapter"].close()
            except Exception:
                pass
        await sink.close()
        logger.info("Kolektor zastaven.")


async def tick_forecast(state: dict) -> None:
    """Přepočet predikce výroby (čtecí) — MVP cadence à 3 h."""
    import time as _t
    now = _t.monotonic()
    if now - state.get("last_forecast", -1e9) < 10800:   # 3 h
        return
    state["last_forecast"] = now
    try:
        await pricing_fx.update_daily()
    except Exception as exc:
        logger.debug("ČNB kurz tick: %s", exc)
    try:
        await forecast_service.refresh_all()
    except Exception as exc:
        logger.warning("Forecast tick selhal: %s", exc)


async def tick_market_and_automation(state: dict) -> None:
    import time as _t
    # obnova spotové ceny (živý feed, pokud není ruční override)
    now = _t.monotonic()
    if now - state.get("last_market", 0.0) >= MARKET_REFRESH:
        state["last_market"] = now
        try:
            st = await market_db.get_state()
            if not st.get("manual"):
                price = await fetch_current_price_czk()
                if price is not None:
                    await market_db.set_live_price(price)
            # čtvrthodinové sloty stahujeme vždy (reálná data i během ručního testu)
            slots = await fetch_day_slots()
            if slots:
                await market_db.upsert_slots(slots)
        except Exception as exc:
            logger.warning("Obnova trhu selhala: %s", exc)
    # vyhodnocení automatizace s aktuální cenou
    try:
        st = await market_db.get_state()
        await evaluate_all(st.get("price"))
    except Exception as exc:
        logger.warning("Automatizace selhala: %s", exc)
    # spínání kontaktu dle SOC (hystereze)
    try:
        await evaluate_outputs()
    except Exception as exc:
        logger.warning("Spínání kontaktu selhalo: %s", exc)

    # plánované odstávky distribuce – 1× denně v nastavenou hodinu (pražský čas)
    import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    try:
        _hour = int(os.getenv("EMS_OUTAGE_HOUR", "7"))
    except ValueError:
        _hour = 7
    _now = _dt.datetime.now(_ZI("Europe/Prague"))
    _day = _now.date().isoformat()
    if _now.hour >= _hour and state.get("last_outage_day") != _day:
        state["last_outage_day"] = _day
        try:
            await refresh_outages_all()
        except Exception as exc:
            logger.warning("Refresh odstávek selhal: %s", exc)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
