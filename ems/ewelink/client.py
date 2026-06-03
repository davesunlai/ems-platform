"""eWeLink Cloud API v2 klient (Sonoff/CoolKit).

Auth: App ID + App Secret z dev.ewelink.cc + přihlášení účtem (e-mail/heslo).
Konfigurace přes env (tajemství v .env, ne v gitu):
  EMS_EWELINK_APPID, EMS_EWELINK_SECRET, EMS_EWELINK_EMAIL,
  EMS_EWELINK_PASSWORD, EMS_EWELINK_REGION (eu|us|as|cn, default eu),
  EMS_EWELINK_COUNTRY (default +420)

Pozn.: kód volá reálný eWeLink cloud — nešlo otestovat z buildovacího prostředí.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import string
import time

logger = logging.getLogger("ems.ewelink")

_cache: dict = {"at": None, "region": None, "exp": 0.0}
_lock = asyncio.Lock()


def configured() -> bool:
    return all(os.getenv(k) for k in
               ("EMS_EWELINK_APPID", "EMS_EWELINK_SECRET", "EMS_EWELINK_EMAIL", "EMS_EWELINK_PASSWORD"))


def _cfg() -> dict:
    return {
        "appid": os.getenv("EMS_EWELINK_APPID", ""),
        "secret": os.getenv("EMS_EWELINK_SECRET", ""),
        "email": os.getenv("EMS_EWELINK_EMAIL", ""),
        "password": os.getenv("EMS_EWELINK_PASSWORD", ""),
        "region": os.getenv("EMS_EWELINK_REGION", "eu"),
        "country": os.getenv("EMS_EWELINK_COUNTRY", "+420"),
    }


def _nonce() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))


def _sign(secret: str, payload: str) -> str:
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()


def _base(region: str) -> str:
    return f"https://{region}-apia.coolkit.cc"


async def _login(client, c: dict) -> tuple[str, str]:
    region = c["region"]
    body = {"email": c["email"], "password": c["password"], "countryCode": c["country"]}
    body_str = json.dumps(body, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "X-CK-Appid": c["appid"],
        "X-CK-Nonce": _nonce(),
        "Authorization": "Sign " + _sign(c["secret"], body_str),
    }
    r = await client.post(_base(region) + "/v2/user/login", content=body_str, headers=headers)
    data = r.json()
    # přesměrování na správný region
    if data.get("error") and data.get("region") and data["region"] != region:
        region = data["region"]
        headers["X-CK-Nonce"] = _nonce()
        r = await client.post(_base(region) + "/v2/user/login", content=body_str, headers=headers)
        data = r.json()
    if data.get("error"):
        raise RuntimeError(f"eWeLink login error {data.get('error')}: {data.get('msg')}")
    at = data["data"]["at"]
    region = data["data"].get("region", region)
    return at, region


async def _ensure_token(client) -> tuple[str, str]:
    if _cache["at"] and _cache["exp"] > time.time():
        return _cache["at"], _cache["region"]
    c = _cfg()
    at, region = await _login(client, c)
    _cache.update({"at": at, "region": region, "exp": time.time() + 6 * 3600})
    return at, region


def _normalize(item: dict) -> dict:
    d = item.get("itemData", item)
    p = d.get("params", {}) or {}
    sw = p.get("switch")
    if sw is None and isinstance(p.get("switches"), list) and p["switches"]:
        sw = p["switches"][0].get("switch")

    def num(key):
        v = p.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "deviceid": d.get("deviceid"),
        "name": d.get("name"),
        "online": bool(d.get("online")),
        "switch": sw,
        "power": num("power"),
        "voltage": num("voltage"),
        "current": num("current"),
    }


async def list_devices() -> list[dict]:
    if not configured():
        raise RuntimeError("eWeLink není nakonfigurován (chybí EMS_EWELINK_* v .env)")
    import httpx
    async with _lock:
        async with httpx.AsyncClient(timeout=15.0) as client:
            at, region = await _ensure_token(client)
            headers = {
                "Authorization": "Bearer " + at,
                "X-CK-Appid": _cfg()["appid"],
                "X-CK-Nonce": _nonce(),
                "Content-Type": "application/json",
            }
            r = await client.get(_base(region) + "/v2/device/thing", headers=headers)
            data = r.json()
            if data.get("error") in (401, 402, 403):  # token vypršel → znovu
                _cache["at"] = None
                at, region = await _ensure_token(client)
                headers["Authorization"] = "Bearer " + at
                headers["X-CK-Nonce"] = _nonce()
                r = await client.get(_base(region) + "/v2/device/thing", headers=headers)
                data = r.json()
            if data.get("error"):
                raise RuntimeError(f"eWeLink chyba {data.get('error')}: {data.get('msg')}")
            things = (data.get("data") or {}).get("thingList", [])
            return [_normalize(t) for t in things]
