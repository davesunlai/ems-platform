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
from ems.api.db import list_devices
from ems.forecast import db as forecast_db
from ems.forecast import service as forecast_service
from ems.pricing import db as pricing_db
from ems.pricing import fx as pricing_fx
from ems.planner import db as planner_db
from ems.planner import service as planner_service
from ems.notify import dispatch as notify_dispatch
from ems.outputs.engine import evaluate_outputs
from ems.outages.service import refresh_all as refresh_outages_all
from .config import build_adapter, build_sink

logging.basicConfig(
    level=os.getenv("EMS_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("ems.collector")

POLL_INTERVAL = float(os.getenv("EMS_POLL_INTERVAL", "10"))
# Po ručním povelu (Stop / Nabíjet / Vybíjet) nech plánovač modul takto dlouho na pokoji:
MANUAL_OVERRIDE_SEC = float(os.getenv("EMS_MANUAL_OVERRIDE_SEC", "1800"))
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
        # Zatoulaný keepalive „poke" (z doby před Stopem) nesmí znovu nahodit force.
        if c["action"] == "force_poke":
            try:
                stt = (await control_db.get_states([c["module_id"]])).get(c["module_id"]) or {}
                if stt.get("action") not in ("force_charge", "force_discharge"):
                    await control_db.complete(c["id"], True, {"skipped": "modul neforcuje"})
                    continue
            except Exception:
                pass
        try:
            res = await dispatch_command(adapter, c["action"], c["params"] or {})
            await control_db.complete(c["id"], True, res if isinstance(res, dict) else {"result": res})
            # aktuální stav zapisuj jen pro provozní režimy (ne limity/čtení)
            if c["action"] in ("force_charge", "force_discharge", "stop", "spiral"):
                try:
                    act = "idle" if c["action"] == "stop" else c["action"]
                    await control_db.set_state(c["module_id"], act, c["params"] or {},
                                               source=(c["params"] or {}).get("source", "manual"),
                                               username=c.get("username"))
                except Exception:
                    pass
                # notifikace operace (spuštění režimu i návrat do Self-Use)
                if c["action"] in ("force_charge", "force_discharge", "spiral", "stop"):
                    try:
                        from ems.alerts import db as alerts_db
                        loc_id = next((d.get("locality_id") for d in await list_devices()
                                       if d["device_id"] == c["module_id"]), None)
                        p = c["params"] or {}
                        pw = p.get("power")
                        label = {"force_charge": "Vynucené nabíjení", "force_discharge": "Vybíjení do sítě",
                                 "spiral": "Spirála", "stop": "Návrat do Self-Use (stop)"}[c["action"]]
                        if c["action"] == "stop":
                            detail = "řízení zastaveno · " + (p.get("source") or "ručně")
                        else:
                            detail = (f"{pw/100:.1f} kW" if pw is not None else "") + \
                                     (f" · {p.get('source')}" if p.get("source") and p.get("source") != "manual" else " · ručně")
                        kind = "stop" if c["action"] == "stop" else c["action"]
                        await alerts_db.record_event(loc_id, kind, f"{label} – {c['module_id']}", detail)
                        await notify_dispatch.notify_new_alerts()  # rozešli hned, nečekej na tick
                    except Exception:
                        pass
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
        await control_db.ensure_state_schema()
        await control_db.ensure_spot_rule_schema()
        await forecast_db.ensure_schema()
        await pricing_db.ensure_schema()
        await planner_db.ensure_schema()
        from ems.alerts import db as alerts_db
        await alerts_db.ensure_schema()
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
            await tick_planner(state)
            await tick_force_keepalive(state)
            await tick_notify(state)
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


async def tick_planner(state: dict) -> None:
    """Přepočet plánu (à 30 min) + výkon: enqueue aktuální akce při změně
    pro lokality se zapnutým plánovačem. Force jede BEZ syrového výkonu —
    nabíjení/vybíjení probíhá na nastavených limitech proudu (obejde 43136)."""
    import time as _t
    now = _t.monotonic()
    if now - state.get("last_planner", -1e9) >= 1800:
        state["last_planner"] = now
        try:
            await planner_service.run_all()
        except Exception as exc:
            logger.warning("Planner přepočet selhal: %s", exc)
    try:
        controlled = await planner_service.controlled_devices()
        if not controlled:
            return
        all_devs = [d for ds in controlled.values() for d in ds]
        states = await control_db.get_states(all_devs)
        for lid, devs in controlled.items():
            ca = await planner_db.current_action(lid)
            if not ca:
                continue
            act = ca["action"]
            power_reg = int(round(abs(ca.get("battery_kw") or 0) * 100))   # kW -> registr (10 W/jedn.)
            if act == "charge_grid":
                desired, cmd, params = "force_charge", "force_charge", {"power": power_reg, "source": "planner"}
            elif act == "discharge_grid":
                desired, cmd, params = "force_discharge", "force_discharge", {"power": power_reg, "source": "planner"}
            else:
                desired, cmd, params = "idle", "stop", {"source": "planner"}
            for dev in devs:
                st = states.get(dev) or {}
                # Ruční přebití: po manuálním povelu nech plánovač modul 30 min na pokoji
                # (jinak by planner okamžitě přebil tvůj Stop / ruční zásah).
                since = st.get("since")
                if st.get("source") == "manual" and since is not None:
                    try:
                        from datetime import datetime, timezone
                        if (datetime.now(timezone.utc) - since).total_seconds() < MANUAL_OVERRIDE_SEC:
                            continue
                    except Exception:
                        pass
                cur = st.get("action", "idle")
                if cur != desired:
                    await control_db.enqueue(dev, cmd, params, username="planner")
                    logger.info("Planner lok %s modul %s: %s -> %s (%s)", lid, dev, cur, desired, ca.get("reason"))
    except Exception as exc:
        logger.debug("Planner výkon: %s", exc)


async def tick_force_keepalive(state: dict) -> None:
    """Deadman: 43135 se po ~5 min nuluje → každé 4 min přiťukni aktivní force,
    aby vynucené nabíjení/vybíjení nespadlo (a dashboard nelhal)."""
    import time as _t
    now = _t.monotonic()
    if now - state.get("last_keepalive_check", 0.0) < 60:
        return
    state["last_keepalive_check"] = now
    try:
        solis = [d["device_id"] for d in await list_devices() if d.get("adapter") == "solis"]
        if not solis:
            return
        states = await control_db.get_states(solis)
        poked = state.setdefault("force_poked", {})
        import time as _w
        wall = _w.time()
        for mod, st in states.items():
            act = st.get("action")
            if act in ("force_charge", "force_discharge"):
                mode = 1 if act == "force_charge" else 2
                if wall - poked.get(mod, 0.0) > 240:
                    await control_db.enqueue(mod, "force_poke", {"mode": mode}, username="keepalive")
                    poked[mod] = wall
            else:
                poked.pop(mod, None)
    except Exception as exc:
        logger.debug("force keepalive: %s", exc)


async def tick_notify(state: dict) -> None:
    """Rozeslání notifikací o nových výstrahách (e-mail) à 5 min."""
    import time as _t
    now = _t.monotonic()
    if now - state.get("last_notify", -1e9) < 60:
        return
    state["last_notify"] = now
    try:
        await notify_dispatch.notify_new_alerts()
    except Exception as exc:
        logger.warning("Notify dispatch selhal: %s", exc)


async def _latest_soc(device_id: str):
    """Poslední SoC celého úložiště (battery_soc), případně průměr packů."""
    from ems.api.db import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            "SELECT value FROM samples WHERE device_id=$1 AND metric='battery_soc' "
            "AND time > now() - interval '10 minutes' ORDER BY time DESC LIMIT 1", device_id)
        if v is None:
            v = await conn.fetchval(
                "SELECT avg(value) FROM (SELECT DISTINCT ON (metric) value FROM samples "
                "WHERE device_id=$1 AND metric IN ('battery_soc_1','battery_soc_2') "
                "AND time > now() - interval '10 minutes' ORDER BY metric, time DESC) t", device_id)
    return float(v) if v is not None else None


async def evaluate_spot_discharge(price, skip_devices=None) -> None:
    """Spotové auto-vybíjení do sítě (Solis force_discharge).

    Hystereze: zapni při spot ≥ price_on, vypni při spot < price_off.
    Podlaha SoC: nevybíjej pod soc_floor (a vypni, když na ni klesne).
    Respektuje plánovač (skip) i ruční override (MANUAL_OVERRIDE_SEC).
    Vlastní povely jdou se source='spot' (ručně/Stop jde přebít kdykoli).
    """
    if price is None:
        return
    from datetime import datetime, timezone
    skip = set(skip_devices or [])
    rules = await control_db.list_spot_rules_enabled()
    if not rules:
        return
    states = await control_db.get_states([r["module_id"] for r in rules])
    for r in rules:
        dev = r["module_id"]
        if dev in skip:           # plánovač má přednost
            continue
        st = states.get(dev) or {}
        # ruční přebití: po manuálním povelu nech modul chvíli na pokoji
        since = st.get("since")
        if st.get("source") == "manual" and since:
            try:
                s = since if hasattr(since, "tzinfo") else datetime.fromisoformat(since)
                if (datetime.now(timezone.utc) - s).total_seconds() < MANUAL_OVERRIDE_SEC:
                    continue
            except Exception:
                pass
        soc = await _latest_soc(dev)
        cur = st.get("action", "idle")
        floor = float(r["soc_floor"])
        if bool(r["active"]):
            low_soc = soc is not None and soc <= floor
            if price < float(r["price_off"]) or low_soc:
                if cur == "force_discharge" and st.get("source") in (None, "spot"):
                    reason = (f"SoC {soc:.0f}% ≤ podlaha {floor:.0f}%" if low_soc
                              else f"spot {price:.0f} < vyp {float(r['price_off']):.0f} Kč/MWh")
                    prm = {"source": "spot", "name": "Spotové vybíjení", "reason": reason,
                           "values": {"spot": round(price), "vyp_pod": float(r["price_off"]),
                                      "SoC_%": (round(soc, 1) if soc is not None else None), "podlaha_SoC_%": floor}}
                    cmd_id = await control_db.enqueue(dev, "stop", prm, username="spot")
                    await control_db.record("spot", dev, "stop", prm, True, {"queued": cmd_id})
                    logger.info("Spot-vybíjení %s STOP: %s", dev, reason)
                await control_db.set_spot_rule_active(dev, False)
        else:
            if price >= float(r["price_on"]) and (soc is None or soc > floor):
                if cur != "force_discharge":
                    power_reg = int(round(float(r["power_kw"]) * 100))
                    reason = f"spot {price:.0f} ≥ zap {float(r['price_on']):.0f} Kč/MWh"
                    prm = {"power": power_reg, "source": "spot", "name": "Spotové vybíjení", "reason": reason,
                           "values": {"spot": round(price), "zap_od": float(r["price_on"]),
                                      "vykon_kW": float(r["power_kw"]),
                                      "SoC_%": (round(soc, 1) if soc is not None else None), "podlaha_SoC_%": floor}}
                    cmd_id = await control_db.enqueue(dev, "force_discharge", prm, username="spot")
                    await control_db.record("spot", dev, "force_discharge", prm, True, {"queued": cmd_id})
                    logger.info("Spot-vybíjení %s START %.1f kW: %s", dev, float(r["power_kw"]), reason)
                await control_db.set_spot_rule_active(dev, True)


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
    # vyhodnocení automatizace s aktuální cenou (kromě modulů řízených plánovačem)
    try:
        st = await market_db.get_state()
        controlled = await planner_service.controlled_devices()
        skip = [d for devs in controlled.values() for d in devs]
        await evaluate_all(st.get("price"), skip_devices=skip)
    except Exception as exc:
        logger.warning("Automatizace selhala: %s", exc)
    # spotové auto-vybíjení do sítě (Solis force_discharge, hystereze + podlaha SoC)
    try:
        await evaluate_spot_discharge(st.get("price"), skip_devices=skip)
    except Exception as exc:
        logger.warning("Spotové vybíjení selhalo: %s", exc)
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
