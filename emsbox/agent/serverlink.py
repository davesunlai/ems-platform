"""HTTPS spojení na teraems.com: pair, config (ETag), telemetry, heartbeat.

Box jen PUSHUJE ven (žádný inbound port). Credentials /data/credentials.json
(chmod 600). Backoff při chybách řeší volající (main), tady jen čisté requesty.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx

CRED_PATH = os.environ.get("EMSBOX_CRED", "/data/credentials.json")


def load_credentials() -> dict | None:
    p = Path(CRED_PATH)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def save_credentials(server: str, box_id: int, token: str) -> None:
    p = Path(CRED_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"server": server.rstrip("/"), "box_id": box_id, "box_token": token}))
    os.chmod(p, 0o600)


class ServerLink:
    def __init__(self, cred: dict, timeout: float = 25.0):
        self.server = cred["server"]
        self.box_id = int(cred["box_id"])
        self._headers = {"Authorization": f"Bearer {cred['box_token']}"}
        self._client = httpx.AsyncClient(timeout=timeout)
        self._config_etag: str | None = None

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    async def pair(server: str, code: str, hw_info: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=25.0) as c:
            r = await c.post(f"{server.rstrip('/')}/api/emsbox/pair",
                             json={"code": code, "hw_info": hw_info or {}})
            r.raise_for_status()
            return r.json()

    async def get_config(self) -> dict | None:
        """None = 304 beze změny."""
        h = dict(self._headers)
        if self._config_etag:
            h["If-None-Match"] = self._config_etag
        r = await self._client.get(f"{self.server}/api/emsbox/{self.box_id}/config", headers=h)
        if r.status_code == 304:
            return None
        r.raise_for_status()
        self._config_etag = r.headers.get("etag")
        return r.json()

    async def send_telemetry(self, rows: list[dict], box_time: str) -> dict:
        body = {"box_id": self.box_id, "batch_id": str(uuid.uuid4()), "box_time": box_time,
                "rows": [{k: v for k, v in r.items() if k != "_id"} for r in rows]}
        r = await self._client.post(f"{self.server}/api/ingest/v1/telemetry",
                                    json=body, headers=self._headers)
        r.raise_for_status()
        return r.json()

    async def heartbeat(self, body: dict) -> None:
        body["box_id"] = self.box_id
        r = await self._client.post(f"{self.server}/api/ingest/v1/heartbeat",
                                    json=body, headers=self._headers)
        r.raise_for_status()
