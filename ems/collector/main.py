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
from ems.market.spot import fetch_current_price_czk
from ems.automation import db as automation_db
from ems.automation.engine import evaluate_all
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


async def poll_device(adapter, sink) -> None:
    try:
        reading = await adapter.read()
        await sink.write(reading_to_samples(reading))
        if reading.states and hasattr(sink, "write_states"):
            await sink.write_states(reading.device_id, reading.states)
    except Exception as exc:
        logger.warning("Čtení '%s' selhalo: %s", getattr(adapter, "device_id", "?"), exc)


async def reconcile(active: dict, sink) -> None:
    """Srovná běžící adaptéry s aktivními moduly v DB."""
    try:
        wanted = await modules_db.list_enabled_reads()
    except Exception as exc:
        logger.warning("Načtení registru modulů selhalo, ponechávám stávající: %s", exc)
        return
    wanted_by_id = {m.id: m for m in wanted}

    # připoj nové
    for mid, m in wanted_by_id.items():
        if mid not in active:
            try:
                adapter = build_adapter(_module_to_device(m))
                await adapter.connect()
                active[mid] = adapter
                logger.info("Modul připojen: %s (adaptér=%s)", mid, m.adapter)
            except Exception as exc:
                logger.warning("Připojení modulu '%s' selhalo (zkusím příště): %s", mid, exc)

    # odpoj odebrané/vypnuté
    for mid in list(active):
        if mid not in wanted_by_id:
            try:
                await active[mid].close()
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
        await automation_db.ensure_schema()
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
                await asyncio.gather(*(poll_device(a, sink) for a in active.values()))
            await tick_market_and_automation(state)
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass
    finally:
        for a in active.values():
            try:
                await a.close()
            except Exception:
                pass
        await sink.close()
        logger.info("Kolektor zastaven.")


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
        except Exception as exc:
            logger.warning("Obnova trhu selhala: %s", exc)
    # vyhodnocení automatizace s aktuální cenou
    try:
        st = await market_db.get_state()
        await evaluate_all(st.get("price"))
    except Exception as exc:
        logger.warning("Automatizace selhala: %s", exc)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
