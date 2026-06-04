"""Načítání plánovaných odstávek distribuce — ČEZ Distribuce.

Zdroj: anonymní endpoint distribučního portálu (DIP), bez přihlášení.
  1) GET  .../anonymous/rest-auth-api?path=/token/get      -> X-Request-Token
  2) POST .../anonymous/vyhledani-odstavek?path=shutdown-search
        body: {"eans":[...]} | {"meterNumbers":[...]} | {"psc","mesto","ulice"}

Odstávky se publikují min. 15 dní předem → stačí stahovat 1× denně.
Bázové rozhraní OutageProvider umožní později přidat EGD/PRE.
"""
from __future__ import annotations

import datetime as dt
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

logger = logging.getLogger("ems.outages")
PRAGUE = ZoneInfo("Europe/Prague")


@dataclass(slots=True)
class Outage:
    distributor: str
    number: str
    start: dt.datetime
    end: dt.datetime
    eans: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.distributor}:{self.number}:{self.start.date().isoformat()}"


class OutageProvider(ABC):
    distributor: str

    @abstractmethod
    async def fetch(self, query: dict) -> list[Outage]:
        ...


class CezOutageProvider(OutageProvider):
    distributor = "CEZ"
    BASE = "https://dip.cezdistribuce.cz/irj/portal/anonymous"
    TOKEN_URL = f"{BASE}/rest-auth-api?path=/token/get"
    SEARCH_URL = f"{BASE}/vyhledani-odstavek?path=shutdown-search"

    def __init__(self, *, timeout: float = 20.0) -> None:
        self._timeout = timeout
        self._token: str | None = None

    async def fetch(self, query: dict) -> list[Outage]:
        """query = {"eans":[...]} | {"meterNumbers":[...]} | {"psc","mesto","ulice"}"""
        if not query:
            return []
        import httpx
        async with httpx.AsyncClient(timeout=self._timeout,
                                     headers={"User-Agent": "TERA-EMS"},
                                     follow_redirects=True) as client:
            await self._ensure_token(client)
            data = await self._search(client, query)
        eans = query.get("eans", []) if isinstance(query, dict) else []
        return [self._normalize(o, eans) for o in self._iter_outages(data)]

    async def _ensure_token(self, client) -> None:
        r = await client.get(self.TOKEN_URL)
        r.raise_for_status()
        try:
            payload = r.json()
        except ValueError:
            payload = r.text
        if isinstance(payload, dict):
            self._token = payload.get("data") or payload.get("token")
        else:
            self._token = str(payload).strip().strip('"')
        if not self._token:
            raise RuntimeError("ČEZ: nepodařilo se získat X-Request-Token")

    async def _search(self, client, body: dict) -> Any:
        r = await client.post(self.SEARCH_URL, json=body,
                              headers={"X-Request-Token": self._token or ""})
        if r.status_code == 401:
            await self._ensure_token(client)
            r = await client.post(self.SEARCH_URL, json=body,
                                  headers={"X-Request-Token": self._token or ""})
        r.raise_for_status()
        payload = r.json()
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    @staticmethod
    def _iter_outages(data: Any) -> Iterable[dict]:
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("outages", "shutdowns", "items", "results", "list"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    def _normalize(self, o: dict, eans: Sequence[str]) -> Outage:
        start, end = self._parse_window(o)
        return Outage(
            distributor=self.distributor,
            number=str(o.get("number") or o.get("cislo") or ""),
            start=start, end=end, eans=list(eans),
            locations=self._collect_locations(o), raw=o,
        )

    @staticmethod
    def _parse_window(o: dict) -> tuple[dt.datetime, dt.datetime]:
        date_val = o.get("dateFormatted") or o.get("date") or ""
        d = None
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                d = dt.datetime.strptime(str(date_val)[:len(fmt) + 2], fmt).date()
                break
            except ValueError:
                continue
        if d is None:
            d = dt.date.today()
        tf = (o.get("timeFormatted") or "").replace(" ", "")
        sh, sm, eh, em = 0, 0, 23, 59
        if "-" in tf:
            a, b = tf.split("-", 1)
            try:
                sh, sm = map(int, a.split(":"))
                eh, em = map(int, b.split(":"))
            except ValueError:
                pass
        start = dt.datetime(d.year, d.month, d.day, sh, sm, tzinfo=PRAGUE)
        end = dt.datetime(d.year, d.month, d.day, eh, em, tzinfo=PRAGUE)
        return start, end

    @staticmethod
    def _collect_locations(o: dict) -> list[str]:
        out: list[str] = []
        for part in (o.get("parts") or []):
            for street in (part.get("streets") or []):
                name = street.get("street") or street.get("name") or ""
                nums = street.get("streetNumbers") or street.get("numbers") or []
                nums_s = ", ".join(str(n.get("number") if isinstance(n, dict) else n) for n in nums)
                out.append(f"{name} {nums_s}".strip() if name or nums_s else "")
        return [x for x in out if x]
