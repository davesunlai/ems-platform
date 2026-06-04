"""eWeLink Cloud API v2 klient (Sonoff/CoolKit) — OAuth2.

Aplikace z eWeLink developer centra nesmí přihlášení e-mailem/heslem
(/v2/user/login → chyba 407), proto OAuth2 authorization-code flow:
  1) uživatel je přesměrován na přihlašovací stránku eWeLink (build_login_url),
  2) eWeLink přesměruje zpět na redirectUrl s ?code=&region=,
  3) server vymění code za access/refresh token (exchange_code) a uloží ho,
  4) access token (Bearer) volá /v2/device/thing, ovládání atd.; obnova přes refresh.

Konfigurace (env, tajemství v .env):
  EMS_EWELINK_APPID, EMS_EWELINK_SECRET, EMS_EWELINK_REGION (eu|us|as|cn, default eu)
  EMS_BASE_URL (pro sestavení redirect URL: {base}/api/ewelink/callback)
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import json
import logging
import os
import secrets
import string
import time
from urllib.parse import quote

from . import store

logger = logging.getLogger("ems.ewelink")
_lock = asyncio.Lock()
LOGIN_PAGE = "https://c2ccdn.coolkit.cc/oauth/index.html"
_pending_states: dict[str, float] = {}


def configured() -> bool:
    return bool(os.getenv("EMS_EWELINK_APPID") and os.getenv("EMS_EWELINK_SECRET"))


def _appid() -> str:
    return os.getenv("EMS_EWELINK_APPID", "")


def _secret() -> str:
    return os.getenv("EMS_EWELINK_SECRET", "")


def _region() -> str:
    return os.getenv("EMS_EWELINK_REGION", "eu")


def _redirect_url() -> str:
    base = os.getenv("EMS_BASE_URL", "http://localhost:8080").rstrip("/")
    return f"{base}/api/ewelink/callback"


def _nonce() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))


def _sign(payload: str) -> str:
    mac = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()


def _base(region: str) -> str:
    return f"https://{region}-apia.coolkit.cc"


def build_login_url() -> str:
    seq = str(int(time.time() * 1000))
    state = secrets.token_urlsafe(16)
    _pending_states[state] = time.time()
    # úklid starých states
    for s, t in list(_pending_states.items()):
        if time.time() - t > 600:
            _pending_states.pop(s, None)
    sign = _sign(f"{_appid()}_{seq}")
    return (
        f"{LOGIN_PAGE}?clientId={quote(_appid())}&seq={seq}"
        f"&authorization={quote(sign)}&redirectUrl={quote(_redirect_url(), safe='')}"
        f"&grantType=authorization_code&state={quote(state)}&nonce={_nonce()}"
    )


def _ms_to_dt(ms) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(float(ms) / 1000, tz=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


async def exchange_code(code: str, region: str | None) -> None:
    import httpx
    region = region or _region()
    body = {"grantType": "authorization_code", "code": code, "redirectUrl": _redirect_url()}
    body_str = json.dumps(body, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "X-CK-Appid": _appid(),
        "X-CK-Nonce": _nonce(),
        "Authorization": "Sign " + _sign(body_str),
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(_base(region) + "/v2/user/oauth/token", content=body_str, headers=headers)
        data = r.json()
    if data.get("error"):
        raise RuntimeError(f"eWeLink token error {data.get('error')}: {data.get('msg')}")
    d = data["data"]
    await store.save_token(
        d["accessToken"], d["refreshToken"], d.get("region", region),
        _ms_to_dt(d.get("atExpiredTime")), _ms_to_dt(d.get("rtExpiredTime")))
    logger.info("eWeLink: token uložen (region %s)", d.get("region", region))


async def _refresh(client, tok: dict) -> dict:
    body = {"rt": tok["refresh_token"]}
    body_str = json.dumps(body, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "X-CK-Appid": _appid(),
        "X-CK-Nonce": _nonce(),
        "Authorization": "Sign " + _sign(body_str),
    }
    r = await client.post(_base(tok["region"]) + "/v2/user/refresh", content=body_str, headers=headers)
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"eWeLink refresh error {data.get('error')}: {data.get('msg')}")
    d = data["data"]
    at, rt = d["at"], d.get("rt", tok["refresh_token"])
    await store.save_token(at, rt, tok["region"], _ms_to_dt(d.get("atExpiredTime")), tok.get("rt_expire"))
    return {**tok, "access_token": at, "refresh_token": rt}


async def _valid_token(client) -> dict:
    tok = await store.get_token()
    if not tok:
        raise RuntimeError("eWeLink není připojen – nejdřív se přihlas přes Připojit eWeLink.")
    now = dt.datetime.now(dt.timezone.utc)
    if tok["at_expire"] and tok["at_expire"] <= now + dt.timedelta(minutes=5):
        tok = await _refresh(client, tok)
    return tok


async def connected() -> bool:
    return (await store.get_token()) is not None


async def _get(client, tok: dict, path: str) -> dict:
    headers = {
        "Authorization": "Bearer " + tok["access_token"],
        "X-CK-Appid": _appid(),
        "X-CK-Nonce": _nonce(),
        "Content-Type": "application/json",
    }
    r = await client.get(_base(tok["region"]) + path, headers=headers)
    return r.json()


async def _families(client, tok: dict) -> list[str]:
    data = await _get(client, tok, "/v2/family")
    if data.get("error"):
        return []
    return [f.get("id") for f in (data.get("data") or {}).get("familyList", []) if f.get("id")]


async def _things_in(client, tok: dict, fid: str | None) -> list[dict]:
    q = "/v2/device/thing?num=0" + (f"&familyid={fid}" if fid else "")
    data = await _get(client, tok, q)
    if data.get("error"):
        return []
    return (data.get("data") or {}).get("thingList", [])


async def list_devices() -> list[dict]:
    if not configured():
        raise RuntimeError("eWeLink není nakonfigurován (chybí EMS_EWELINK_APPID/SECRET v .env)")
    import httpx
    async with _lock:
        async with httpx.AsyncClient(timeout=20.0) as client:
            tok = await _valid_token(client)
            # ověř token jedním lehkým dotazem, případně obnov
            probe = await _get(client, tok, "/v2/family")
            if probe.get("error") in (401, 402, 403):
                tok = await _refresh(client, tok)
            families = await _families(client, tok)
            things: dict[str, dict] = {}
            sources = families if families else [None]
            for fid in sources:
                for t in await _things_in(client, tok, fid):
                    d = t.get("itemData", t)
                    did = d.get("deviceid")
                    if did:
                        things[did] = t
            return [_normalize(t) for t in things.values()]


async def set_switch(deviceid: str, on: bool) -> None:
    if not configured():
        raise RuntimeError("eWeLink není nakonfigurován")
    import httpx
    async with _lock:
        async with httpx.AsyncClient(timeout=15.0) as client:
            tok = await _valid_token(client)
            body = {"type": 1, "id": deviceid, "params": {"switch": "on" if on else "off"}}
            body_str = json.dumps(body, separators=(",", ":"))
            headers = {
                "Authorization": "Bearer " + tok["access_token"],
                "X-CK-Appid": _appid(),
                "X-CK-Nonce": _nonce(),
                "Content-Type": "application/json",
            }
            r = await client.post(_base(tok["region"]) + "/v2/device/thing/status",
                                  content=body_str, headers=headers)
            data = r.json()
            if data.get("error"):
                raise RuntimeError(f"eWeLink ovládání chyba {data.get('error')}: {data.get('msg')}")


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
