"""Zdroj spotových cen (ČR / trh OTE).

Default provider: spotovaelektrina.cz (aktuální cena v Kč/MWh, zdarma).
Pro testování lze cenu nastavit ručně (manual override) přes API/DB.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("ems.market")

ACTUAL_PRICE_URL = "https://spotovaelektrina.cz/api/v1/price/get-actual-price-czk"
DAY_PRICES_URL = "https://spotovaelektrina.cz/api/v1/price/get-prices-json"
QH_PRICES_URL = "https://spotovaelektrina.cz/api/v1/price/get-prices-json-qh"
# Záložní zdroj (v1.2.0, 25. 10. 2026: spotovaelektrina.cz vracela frantově IP prázdné pole —
# tichý blok IP): oficiální OTE denní trh, JSON pro graf; EUR/MWh → × kurz ČNB (pricing.fx).
OTE_CHART_URL = "https://www.ote-cr.cz/cs/kratkodobe-trhy/elektrina/denni-trh/@@chart-data"
_UA = {"User-Agent": "TERA-EMS/1 (+https://teraems.com; energy management, 1 req / 30 min)"}


async def fetch_ote_day_slots(day_date, eur_czk: float) -> list[dict]:
    """OTE denní trh pro daný den → [{start, price Kč/MWh}] (15min sloty; 24 h hodnoty se rozkopírují).
    Struktura: {"data": {"dataLine": [{"title": "Cena (EUR/MWh)", "point": [{"x": 1, "y": 95.1}, …]}, …]}}."""
    from datetime import datetime, timedelta, time as _time, timezone
    from zoneinfo import ZoneInfo
    import httpx
    tz = ZoneInfo("Europe/Prague")
    async with httpx.AsyncClient(timeout=20.0, headers=_UA, follow_redirects=True) as client:
        r = await client.get(OTE_CHART_URL, params={"report_date": day_date.isoformat()})
        r.raise_for_status()
        data = r.json()
    lines = ((data or {}).get("data") or {}).get("dataLine") or []
    if not lines:
        logger.info("OTE %s: zatím nepublikováno (dataLine prázdné)", day_date)
        return []
    series = None
    for ln in lines:
        title = str(ln.get("title", "")).lower()
        if "cena" in title or "price" in title or "eur" in title:
            series = ln.get("point") or []
            break
    if not series and lines:
        series = lines[0].get("point") or []
    pts = []
    for p in series or []:
        try:
            pts.append((int(float(p.get("x"))), float(p.get("y"))))
        except (TypeError, ValueError, AttributeError):
            continue
    if not pts:
        logger.warning("OTE %s: nerozpoznaná struktura: %s", day_date, str(data)[:300])
        return []
    pts.sort()
    n = len(pts)
    # Den má 96 čtvrthodin, při změně času 100 (podzim) / 92 (jaro) — krok je VŽDY 15 min
    # (hodinová data = 23–25 bodů → 60 min). Sloty skládáme v UTC od lokální půlnoci, aby
    # přechod času nerozhodil mřížku (wall-clock aritmetika by 25. hodinu přeskočila).
    step = 15 if n > 30 else 60
    base_utc = datetime.combine(day_date, _time(0, 0)).replace(tzinfo=tz).astimezone(timezone.utc)
    out = []
    for i, (_, eur) in enumerate(pts):
        czk = eur * eur_czk
        for q in range(0, step, 15):
            out.append({"start": (base_utc + timedelta(minutes=i * step + q)).astimezone(tz).isoformat(),
                        "price": round(czk, 2)})
    return out


async def fetch_ote_slots_fallback() -> list[dict]:
    """Dnešek + zítřek z OTE (zítřek je publikovaný cca po 13:00; prázdný výsledek je normální)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    try:
        from ems.pricing import db as pdb
        fx = await pdb.latest_fx()
        rate = float(fx["eur_czk"]) if fx and fx.get("eur_czk") else None
    except Exception:
        rate = None
    if not rate:
        try:
            from ems.pricing import fx as pfx
            rate = await pfx.update_daily()
        except Exception:
            rate = None
    if not rate:
        logger.warning("OTE fallback: chybí kurz EUR/CZK (ČNB)")
        return []
    today = datetime.now(ZoneInfo("Europe/Prague")).date()
    out = []
    for d in (today, today + timedelta(days=1)):
        try:
            out += await fetch_ote_day_slots(d, rate)
        except Exception as exc:
            logger.info("OTE %s: %s", d, exc)
    if out:
        logger.info("Spot: záložní zdroj OTE, %d slotů (kurz %.3f)", len(out), rate)
    return out


async def fetch_current_price_czk() -> float | None:
    """Vrátí aktuální spotovou cenu v Kč/MWh, nebo None při chybě."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0, headers=_UA) as client:
            r = await client.get(ACTUAL_PRICE_URL)
            r.raise_for_status()
            txt = r.text.strip()
            try:
                return float(txt)
            except ValueError:
                data = r.json()
                if isinstance(data, (int, float)):
                    return float(data)
                if isinstance(data, dict):
                    for k in ("price", "priceCZK", "value", "data"):
                        if k in data and isinstance(data[k], (int, float)):
                            return float(data[k])
        return None
    except Exception as exc:
        logger.warning("Načtení spotové ceny selhalo: %s", exc)
        return None


async def fetch_day_prices() -> dict | None:
    """Vrátí hodinovou křivku cen pro dnešek a zítřek (Kč/MWh), nebo None.

    Zítřek bývá publikovaný cca po 14:00; do té doby může být prázdný.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0, headers=_UA) as client:
            r = await client.get(DAY_PRICES_URL)
            r.raise_for_status()
            data = r.json()

        def conv(arr):
            out = []
            for it in arr or []:
                if not isinstance(it, dict):
                    continue
                hr = it.get("hour", it.get("hourIndex"))
                pr = it.get("priceCZK", it.get("price"))
                if hr is not None and pr is not None:
                    try:
                        out.append({"hour": int(hr), "price": float(pr)})
                    except (TypeError, ValueError):
                        pass
            return sorted(out, key=lambda x: x["hour"])

        today = conv(data.get("hoursToday") or data.get("today"))
        tomorrow = conv(data.get("hoursTomorrow") or data.get("tomorrow"))
        if not today and not tomorrow:
            return None
        return {"today": today, "tomorrow": tomorrow}
    except Exception as exc:
        logger.warning("Načtení denní křivky selhalo: %s", exc)
        return None


async def fetch_day_slots() -> list[dict] | None:
    """Čtvrthodinové sloty cen pro dnešek+zítřek jako [{start, price}] (Kč/MWh).

    start = ISO čas začátku 15min slotu v místním pásmu. Trh OTE je od 10/2025
    čtvrthodinový; když QH endpoint selže, použije se hodinový a rozkopíruje
    do čtyř čtvrthodin (přibližné, ale UI zůstane funkční).
    """
    from datetime import datetime, timedelta, time as _time
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Prague")
    today = datetime.now(tz).date()

    def mk(day_date, minute_of_day, price):
        start = datetime.combine(day_date, _time(0, 0)).replace(tzinfo=tz) + timedelta(minutes=minute_of_day)
        return {"start": start.isoformat(), "price": float(price)}

    def parse_local(s, price):
        try:
            dt = datetime.strptime(s, "%Y-%m-%d, %H:%M:%S").replace(tzinfo=tz)
            return {"start": dt.isoformat(), "price": float(price)}
        except Exception:
            return None

    def from_arr(arr, day_date):
        out = []
        for it in arr or []:
            if not isinstance(it, dict):
                continue
            pr = it.get("priceCZK", it.get("price"))
            if pr is None:
                continue
            if it.get("timeLocalStart"):
                sl = parse_local(it["timeLocalStart"], pr)
                if sl:
                    out.append(sl)
                    continue
            hr = it.get("hour", it.get("hourIndex"))
            q = it.get("quarter", it.get("quarterHour"))
            mn = it.get("minute")
            if hr is None and mn is None:
                continue
            minute = int(hr) * 60 if hr is not None else 0
            if q is not None:
                minute += int(q) * 15
            elif mn is not None:
                minute = (int(hr) * 60 if hr is not None else 0) + int(mn)
            out.append(mk(day_date, minute, pr))
        return out

    slots = []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=12.0, headers=_UA) as client:
            r = await client.get(QH_PRICES_URL)
            r.raise_for_status()
            data = r.json()
        if isinstance(data, dict):
            slots += from_arr(data.get("hoursToday") or data.get("today"), today)
            slots += from_arr(data.get("hoursTomorrow") or data.get("tomorrow"), today + timedelta(days=1))
        elif isinstance(data, list):
            for it in data:
                if isinstance(it, dict) and it.get("timeLocalStart"):
                    sl = parse_local(it["timeLocalStart"], it.get("priceCZK", it.get("price")))
                    if sl:
                        slots.append(sl)
    except Exception as exc:
        logger.warning("Načtení čtvrthodinové křivky selhalo: %s", exc)

    if slots:
        return slots

    # fallback 1: hodinový endpoint rozkopírovaný do čtvrthodin
    hourly = await fetch_day_prices()
    if hourly:
        for key, day_date in (("today", today), ("tomorrow", today + timedelta(days=1))):
            for it in hourly.get(key, []):
                for qi in range(4):
                    slots.append(mk(day_date, int(it["hour"]) * 60 + qi * 15, it["price"]))
    if slots:
        return slots
    # fallback 2: oficiální OTE (nezávislý na spotovaelektrina.cz)
    try:
        slots = await fetch_ote_slots_fallback()
    except Exception as exc:
        logger.warning("OTE fallback selhal: %s", exc)
    return slots or None
