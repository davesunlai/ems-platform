"""BMW CarData klient: Device Code Flow (PKCE), obnova tokenů, REST (x-version v1, 50/den), MQTT stream.

Zdroje (ověřeno 1. 11. 2026): BMW CarData Customer API doc (30. 7. 2026), integrace openHAB/ioBroker/HA.
  auth : POST https://customer.bmwgroup.com/gcdm/oauth/device/code  (client_id, response_type=device_code,
         scope="authenticate_user openid cardata:api:read cardata:streaming:read", code_challenge S256)
         POST https://customer.bmwgroup.com/gcdm/oauth/token (grant_type device_code / refresh_token)
         access/id token 1 h, refresh token 14 dní; odpověď nese `gcid`.
  REST : https://api-cardata.bmwgroup.com  + hlavička x-version: v1, Bearer access_token; 50 dotazů/den.
         GET /customers/vehicles/mappings · GET /customers/vehicles/{vin}/basicData
         GET /customers/vehicles/{vin}/telematicData?containerId=… · POST /customers/containers
  MQTT : customer.streaming-cardata.bmwgroup.com:9000 TLS, MQTT 5, user=gcid, pass=id_token, topic gcid/+ ;
         jeden stream na účet; token 1 h → reconnect po obnově. Zpráva: {"vin"|"entityId", "data": {key: {value, timestamp, unit}}}
Stdlib pro HTTP (urllib), paho-mqtt pro stream. Nic z toho nepíše do auta (read-only API).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import db

logger = logging.getLogger("ems.cars")

AUTH_BASE = "https://customer.bmwgroup.com"
API_BASE = "https://api-cardata.bmwgroup.com"
MQTT_HOST = "customer.streaming-cardata.bmwgroup.com"
MQTT_PORT = 9000
SCOPE = "authenticate_user openid cardata:api:read cardata:streaming:read"
REST_POLL_S = 40 * 60          # REST à 40 min (≈36/den + rezerva)
STREAM_RECONNECT_S = 45 * 60   # id_token platí 1 h → přepojit po obnově


PLUG_FALLBACK_KEYS = (
    "vehicle.body.chargingPort.status", "vehicle.body.chargingPort.combinedStatus", "vehicle.body.chargingPort.statusClearText",
    "vehicle.drivetrain.electricEngine.charging.connectorStatus", "vehicle.powertrain.tractionBattery.charging.port.anyPosition.isPlugged",
    "vehicle.body.chargingPort.dcStatus",
)


class CarDataError(Exception):
    pass


def _post_form(url: str, data: dict, timeout: float = 15) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")[:400]
        try:
            return {"_http": e.code, **json.loads(txt)}
        except Exception:
            return {"_http": e.code, "error": txt}


def _get_json(url: str, token: str, timeout: float = 20) -> dict | list:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "x-version": "v1", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raise CarDataError(f"HTTP {e.code} {url.split('bmwgroup.com')[-1]}: {e.read().decode(errors='replace')[:300]}")


def _post_json(url: str, token: str, body: dict, timeout: float = 20) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "x-version": "v1",
                                          "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raise CarDataError(f"HTTP {e.code} {url.split('bmwgroup.com')[-1]}: {e.read().decode(errors='replace')[:300]}")


# --- Device Code Flow ------------------------------------------------------------
async def start_device_flow(aid: int) -> dict:
    acc = await db.get_account(aid)
    if not acc:
        raise CarDataError("účet neexistuje")
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    res = await asyncio.to_thread(_post_form, f"{AUTH_BASE}/gcdm/oauth/device/code", {
        "client_id": acc["client_id"], "response_type": "device_code", "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    if "device_code" not in res:
        await db.update_account(aid, status="error", last_error=str(res)[:300])
        raise CarDataError(f"device/code: {res}")
    exp = datetime.now(timezone.utc) + timedelta(seconds=int(res.get("expires_in") or 600))
    await db.update_account(aid, device_code=res["device_code"], user_code=res.get("user_code"),
                            verification_uri=res.get("verification_uri_complete") or res.get("verification_uri"),
                            code_verifier=verifier, device_expires_at=exp,
                            poll_interval_s=int(res.get("interval") or 5), status="pending", last_error=None)
    return {"user_code": res.get("user_code"), "verification_uri": res.get("verification_uri_complete") or res.get("verification_uri"),
            "expires_at": exp.isoformat()}


def _apply_tokens(acc_fields: dict, res: dict) -> dict:
    now = datetime.now(timezone.utc)
    acc_fields.update(access_token=res.get("access_token"), refresh_token=res.get("refresh_token") or acc_fields.get("refresh_token"),
                      id_token=res.get("id_token"), gcid=res.get("gcid") or acc_fields.get("gcid"),
                      access_expires_at=now + timedelta(seconds=int(res.get("expires_in") or 3600)),
                      refresh_expires_at=now + timedelta(days=14), status="connected", last_error=None)
    return acc_fields


async def poll_device_flow(aid: int) -> dict:
    """Jeden pokus o výměnu device_code za tokeny (volá UI každých ~5 s, nebo collector)."""
    acc = await db.get_account(aid)
    if not acc or acc["status"] != "pending" or not acc.get("device_code"):
        return {"status": (acc or {}).get("status")}
    if acc.get("device_expires_at") and acc["device_expires_at"] < datetime.now(timezone.utc):
        await db.update_account(aid, status="expired", last_error="kód vypršel — začni znovu")
        return {"status": "expired"}
    res = await asyncio.to_thread(_post_form, f"{AUTH_BASE}/gcdm/oauth/token", {
        "client_id": acc["client_id"], "device_code": acc["device_code"],
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "code_verifier": acc["code_verifier"]})
    if res.get("access_token"):
        fields = _apply_tokens({}, res)
        fields.update(device_code=None, user_code=None, code_verifier=None)
        await db.update_account(aid, **fields)
        logger.info("CarData účet #%s: připojen (gcid %s…)", aid, (fields.get("gcid") or "")[:8])
        return {"status": "connected"}
    err = res.get("error") or res.get("_http")
    if err in ("authorization_pending", "slow_down"):
        return {"status": "pending", "error": err}
    await db.update_account(aid, last_error=str(res)[:300])
    return {"status": "pending", "error": str(err)}


async def ensure_token(aid: int) -> dict | None:
    """Vrátí účet s platným access tokenem; obnoví refresh tokenem, když zbývá < 5 min."""
    acc = await db.get_account(aid)
    if not acc or acc["status"] != "connected" or not acc.get("refresh_token"):
        return None
    exp = acc.get("access_expires_at")
    if exp and exp - datetime.now(timezone.utc) > timedelta(minutes=5):
        return acc
    res = await asyncio.to_thread(_post_form, f"{AUTH_BASE}/gcdm/oauth/token", {
        "client_id": acc["client_id"], "grant_type": "refresh_token", "refresh_token": acc["refresh_token"]})
    if not res.get("access_token"):
        logger.warning("CarData účet #%s: obnova tokenu selhala: %s", aid, str(res)[:200])
        if res.get("_http") in (400, 401):
            await db.update_account(aid, status="expired", last_error=f"refresh token neplatný: {str(res)[:200]}")
        return None
    fields = _apply_tokens({"refresh_token": acc["refresh_token"], "gcid": acc.get("gcid")}, res)
    await db.update_account(aid, **fields)
    acc.update(fields)
    return acc


# --- REST ----------------------------------------------------------------------
async def sync_vehicles(aid: int) -> list[dict]:
    acc = await ensure_token(aid)
    if not acc:
        raise CarDataError("účet není připojen")
    if await db.rest_budget_hit(aid):
        raise CarDataError("denní rozpočet REST (50) vyčerpán")
    res = await asyncio.to_thread(_get_json, f"{API_BASE}/customers/vehicles/mappings", acc["access_token"])
    vins = []
    items = res if isinstance(res, list) else (res.get("mappings") or res.get("vehicles") or res.get("items") or [])
    for it in items:
        vin = (it.get("vin") if isinstance(it, dict) else None) or (it if isinstance(it, str) else None)
        if vin:
            vins.append(vin)
            await db.upsert_vehicle(vin, aid, basic=it if isinstance(it, dict) else {"vin": vin})
    for vin in vins:
        if await db.rest_budget_hit(aid):
            break
        try:
            b = await asyncio.to_thread(_get_json, f"{API_BASE}/customers/vehicles/{vin}/basicData", acc["access_token"])
            model = b.get("modelName") or b.get("model") or b.get("series")
            await db.upsert_vehicle(vin, aid, basic=b, model=model, brand=b.get("brand"))
        except CarDataError as exc:
            logger.info("basicData %s: %s", vin, exc)
    return await db.list_vehicles()


async def _ensure_container(acc: dict, keys: list[str]) -> str | None:
    if acc.get("container_id"):
        return acc["container_id"]
    try:
        res = await asyncio.to_thread(_post_json, f"{API_BASE}/customers/containers", acc["access_token"],
                                      {"name": "TERA EMS", "purpose": "Energy management (home PV / wallbox)",
                                       "technicalDescriptors": keys})
        cid = res.get("containerId") or res.get("id")
        if cid:
            await db.update_account(acc["id"], container_id=cid)
            return cid
        logger.info("CarData container: nečekaná odpověď %s", str(res)[:200])
    except CarDataError as exc:
        logger.info("CarData container create: %s", exc)
    return None


async def poll_rest(aid: int) -> int:
    """Periodické REST čtení telematiky (doplněk streamu; 1× za 40 min)."""
    acc = await ensure_token(aid)
    if not acc:
        return 0
    vehicles = [v for v in await db.list_vehicles() if v["account_id"] == aid and v.get("enabled", True)]
    if not vehicles:
        return 0
    keys = sorted({k for v in vehicles for k in (v.get("key_map") or db.DEFAULT_KEY_MAP).values()})
    cid = await _ensure_container(acc, keys)
    n = 0
    for v in vehicles:
        if await db.rest_budget_hit(aid):
            break
        url = f"{API_BASE}/customers/vehicles/{v['vin']}/telematicData" + (f"?containerId={cid}" if cid else "")
        try:
            res = await asyncio.to_thread(_get_json, url, acc["access_token"])
        except CarDataError as exc:
            logger.info("telematicData %s: %s", v["vin"], exc)
            continue
        data = res.get("telematicData") if isinstance(res, dict) else None
        if isinstance(data, dict):
            n += await db.write_values(v["vin"], data, "rest")
    return n


# --- MQTT stream ---------------------------------------------------------------
class Stream:
    """Jedno MQTT spojení na účet (BMW povoluje jeden stream na gcid). Běží v paho vlákně,
    zprávy se předávají do asyncio fronty."""

    def __init__(self, aid: int, loop: asyncio.AbstractEventLoop):
        self.aid = aid
        self.loop = loop
        self.client = None
        self.queue: asyncio.Queue = asyncio.Queue()
        self.connected_at = None
        self.msgs = 0
        self.last_error = None

    def start(self, gcid: str, id_token: str) -> None:
        import paho.mqtt.client as mqtt
        self.stop()
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"tera-{gcid[:8]}-{secrets.token_hex(3)}",
                        protocol=mqtt.MQTTv5)
        c.username_pw_set(gcid, id_token)
        c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        topic = f"{gcid}/+"

        def on_connect(cl, userdata, flags, rc, props=None):
            ok = (getattr(rc, "value", rc) == 0)
            self.last_error = None if ok else str(rc)
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("connect", ok, str(rc)))
            if ok:
                cl.subscribe(topic, qos=1)

        def on_message(cl, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
            except Exception:
                return
            self.msgs += 1
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("msg", msg.topic, payload))

        def on_disconnect(cl, userdata, flags, rc, props=None):
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("disconnect", False, str(rc)))

        c.on_connect, c.on_message, c.on_disconnect = on_connect, on_message, on_disconnect
        c.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        c.loop_start()
        self.client = c
        self.connected_at = time.monotonic()

    def stop(self) -> None:
        if self.client is not None:
            try:
                self.client.disconnect(); self.client.loop_stop()
            except Exception:
                pass
            self.client = None


_streams: dict[int, Stream] = {}
_last_rest: dict[int, float] = {}
_last_stream_start: dict[int, float] = {}


async def _consume(aid: int, st: Stream) -> None:
    while not st.queue.empty():
        kind, a, b = st.queue.get_nowait()
        if kind == "connect":
            await db.update_account(aid, stream_status=("online" if a else f"chyba: {b}"), stream_since=datetime.now(timezone.utc))
            logger.info("CarData stream #%s: %s", aid, "připojen" if a else f"odmítnut ({b})")
        elif kind == "disconnect":
            await db.update_account(aid, stream_status=f"odpojen ({b})")
        elif kind == "msg":
            topic, payload = a, b
            vin = payload.get("vin") or payload.get("entityId") or topic.split("/")[-1]
            data = payload.get("data") or {}
            if vin and isinstance(data, dict):
                try:
                    await db.upsert_vehicle(vin, aid)
                    n = await db.write_values(vin, data, "stream")
                    await db.update_account(aid, stream_msgs=st.msgs)
                except Exception as exc:
                    logger.debug("stream write %s: %s", vin, exc)


async def tick(state: dict) -> None:
    """Volá collector každý cyklus: pending účty dotáhne, tokeny obnoví, stream drží, REST à 40 min."""
    try:
        accounts = await db.list_accounts()
    except Exception:
        return
    loop = asyncio.get_running_loop()
    now = time.monotonic()
    for acc in accounts:
        aid = acc["id"]
        if acc["status"] == "pending":
            if now - state.get(f"cars_poll_{aid}", 0) >= max(5, acc.get("poll_interval_s") or 5):
                state[f"cars_poll_{aid}"] = now
                try:
                    await poll_device_flow(aid)
                except Exception as exc:
                    logger.debug("device flow #%s: %s", aid, exc)
            continue
        if acc["status"] != "connected":
            continue
        acc2 = await ensure_token(aid)
        if not acc2:
            continue
        st = _streams.get(aid)
        need_start = st is None or st.client is None or (now - _last_stream_start.get(aid, 0) > STREAM_RECONNECT_S)
        if need_start and acc2.get("gcid") and acc2.get("id_token"):
            try:
                if st is None:
                    st = _streams[aid] = Stream(aid, loop)
                st.start(acc2["gcid"], acc2["id_token"])
                _last_stream_start[aid] = now
            except Exception as exc:
                logger.warning("CarData stream #%s start: %s", aid, exc)
                await db.update_account(aid, stream_status=f"chyba: {exc}")
        if st is not None:
            await _consume(aid, st)
        if now - _last_rest.get(aid, -1e9) > REST_POLL_S:
            _last_rest[aid] = now
            try:
                if not [v for v in await db.list_vehicles() if v["account_id"] == aid]:
                    await sync_vehicles(aid)
                await poll_rest(aid)
            except Exception as exc:
                logger.info("CarData REST #%s: %s", aid, exc)


def car_view(v: dict, st: dict) -> dict:
    """Vozidlo + role podle key_map → {soc, range_km, plugged, charging, …} pro UI/plánovač."""
    km = {**db.DEFAULT_KEY_MAP, **(v.get("key_map") or {})}
    out = {"vin": v["vin"], "name": v.get("name") or v.get("model") or v["vin"][-6:], "model": v.get("model"),
           "locality_id": v.get("locality_id"), "wallbox_module_id": v.get("wallbox_module_id"), "keys_received": len(st)}
    last_ts = None
    for role, key in km.items():
        e = st.get(key)
        out[role] = e["value"] if e else None
        if e and (last_ts is None or e["ts"] > last_ts):
            last_ts = e["ts"]
    out["updated_at"] = last_ts
    cap = v.get("capacity_kwh") or (float(out["capacity_kwh"]) if isinstance(out.get("capacity_kwh"), (int, float)) else None)
    out["capacity_kwh"] = cap
    # katalog BMW udává charging.power ve W; některé vozy/integrace hlásí kW → podle jednotky, jinak podle velikosti
    pw = out.get("charging_power_kw")
    if isinstance(pw, (int, float)):
        unit = str((st.get(km["charging_power_kw"]) or {}).get("unit") or "").lower()
        out["charging_power_kw"] = round(pw / 1000.0, 2) if (unit in ("w", "watt") or (not unit and abs(pw) > 100)) else round(float(pw), 2)
    try:
        out["kwh_now"] = round(float(out["soc"]) / 100.0 * cap, 1) if cap and out.get("soc") is not None else None
    except (TypeError, ValueError):
        out["kwh_now"] = None
    try:
        soc, tgt = float(out["soc"]), float(out["target_soc"]) if out.get("target_soc") is not None else 100.0
        out["kwh_to_target"] = round(max(0.0, (tgt - soc) / 100.0 * cap), 1) if cap else None
    except (TypeError, ValueError):
        out["kwh_to_target"] = None
    # BMW: CHARGINGACTIVE / NOCHARGING / FULLYCHARGED / CHARGINGPAUSED / CHARGINGERROR / WAITINGFORCHARGING …
    cs = str(out.get("charging_status") or "").upper().replace("_", "").replace(" ", "")
    out["charging"] = cs.startswith("CHARGINGACTIVE") or cs == "CHARGING" or \
        (isinstance(out.get("charging_power_kw"), (int, float)) and out["charging_power_kw"] > 0.2 and not cs.startswith("NO"))
    p = out.get("plugged")
    if p is None or str(p).upper() in ("INVALID", "-NA-"):
        for alt in PLUG_FALLBACK_KEYS:            # vůz posílá jen variantu, kterou má — vezmi první živou
            e = st.get(alt)
            if e and e.get("value") is not None and str(e["value"]).upper() not in ("INVALID", "-NA-"):
                p = e["value"]
                break
    ps = str(p).upper() if p is not None else ""
    out["plugged_bool"] = (p in (1, 1.0, True, "true") or ps.startswith("CONNECTED") or ps == "PLUGGED") if p is not None and ps not in ("INVALID", "-NA-") else None
    return out
