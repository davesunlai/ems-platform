"""Evaluátor alertů (běží v collectoru à 60 s) — brief §6.

Klíčové chování:
- emsbox offline = stale heartbeat > threshold → JEDEN alert za box.
- POTLAČENÍ BOUŘE: dokud je otevřený 'emsbox offline' event (nebo box hlásí
  status offline), per-device pravidla modulů za tímto boxem se přeskakují.
- device offline: přímé moduly dle stáří poslední telemetrie; moduly za boxem
  dle heartbeat_devices (ok=false / stale last_read_ts).
- Anti-flap: event se zavírá až po 2× threshold v pořádku (ok_since v detail);
  mail při re-open stejného pravidla max 1× / 6 h (alert_rules.last_mail_at).
- Recovery mail při zavření (u boxu vč. počtu dohraných řádků z ingestu).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from ems.api.db import get_pool
from . import db as ebdb

logger = logging.getLogger(__name__)

MAIL_COOLDOWN_H = 6


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _send(rule: dict, locality_id: int, subject: str, body: str) -> None:
    """Mail s cooldownem na pravidlo; příjemci = rule.recipients nebo e-maily uživatelů lokality."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        last = await conn.fetchval("SELECT last_mail_at FROM alert_rules WHERE id = $1", rule["id"])
        if last and _now() - last < timedelta(hours=MAIL_COOLDOWN_H):
            logger.info("Alert %s: mail potlačen (cooldown %s h)", rule["id"], MAIL_COOLDOWN_H)
            return
        await conn.execute("UPDATE alert_rules SET last_mail_at = now() WHERE id = $1", rule["id"])
    recipients = rule.get("recipients") or await ebdb.locality_recipient_emails(locality_id)
    if not recipients:
        logger.warning("Alert %s: žádní příjemci", rule["id"])
        return
    try:
        from ems.notify.email import send_email
        for to in recipients:
            await send_email(to, subject, body)
    except Exception as exc:
        logger.warning("Alert mail selhal: %s", exc)


async def _open_event(conn, rule_id: int, detail: dict) -> int | None:
    ev = await conn.fetchrow(
        "SELECT id FROM alert_events WHERE rule_id = $1 AND closed_at IS NULL", rule_id)
    if ev:
        return None
    return await conn.fetchval(
        "INSERT INTO alert_events (rule_id, detail) VALUES ($1, $2) RETURNING id",
        rule_id, json.dumps(detail))


async def _mark_ok(conn, rule_id: int, threshold_min: int) -> dict | None:
    """Hystereze: první OK tik zapíše ok_since; po 2× threshold OK event zavře a vrátí ho."""
    ev = await conn.fetchrow(
        "SELECT id, opened_at, detail FROM alert_events WHERE rule_id = $1 AND closed_at IS NULL", rule_id)
    if not ev:
        return None
    detail = ev["detail"]
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except Exception:
            detail = {}
    detail = detail or {}
    ok_since = detail.get("ok_since")
    if not ok_since:
        detail["ok_since"] = _now().isoformat()
        await conn.execute("UPDATE alert_events SET detail = $2 WHERE id = $1", ev["id"], json.dumps(detail))
        return None
    if _now() - datetime.fromisoformat(ok_since) >= timedelta(minutes=2 * threshold_min):
        await conn.execute("UPDATE alert_events SET closed_at = now() WHERE id = $1", ev["id"])
        return {"id": ev["id"], "opened_at": ev["opened_at"], "detail": detail}
    return None


async def _clear_ok(conn, rule_id: int) -> None:
    """Stále špatně → zruš rozběhnutou hysterezi."""
    await conn.execute(
        "UPDATE alert_events SET detail = detail - 'ok_since' "
        "WHERE rule_id = $1 AND closed_at IS NULL AND detail ? 'ok_since'", rule_id)


async def evaluate() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rules = [dict(r) for r in await conn.fetch("SELECT * FROM alert_rules WHERE enabled")]
        boxes = {r["id"]: dict(r) for r in await conn.fetch("SELECT * FROM emsbox WHERE status != 'disabled'")}
        mods = {r["id"]: dict(r) for r in await conn.fetch(
            "SELECT id, name, locality_id, emsbox_id, enabled FROM modules")}

        # 1) stav boxů (status sloupec) + množina boxů v bouři
        storm_boxes: set[int] = set()
        for b in boxes.values():
            hb = b["last_heartbeat"]
            stale_min = (_now() - hb).total_seconds() / 60 if hb else 1e9
            if stale_min > 5 and b["status"] == "online":
                await conn.execute("UPDATE emsbox SET status = 'offline' WHERE id = $1", b["id"])
                b["status"] = "offline"
            if b["status"] == "offline":
                storm_boxes.add(b["id"])

        # 2) pravidla
        for rule in rules:
            kind, scope, thr = rule["kind"], rule["scope"], rule["threshold_min"] or 15
            if scope == "emsbox":
                b = boxes.get(rule["target_id"])
                if not b:
                    continue
                hb = b["last_heartbeat"]
                stale_min = (_now() - hb).total_seconds() / 60 if hb else 1e9
                bad = False
                if kind == "offline":
                    bad = stale_min > thr
                elif kind == "rtc_drift":
                    bad = b.get("clock_drift_s") is not None and abs(b["clock_drift_s"]) > 60
                elif kind == "buffer_high":
                    bad = (b.get("buffer_rows") or 0) > 100_000
                if bad:
                    await _clear_ok(conn, rule["id"])
                    eid = await _open_event(conn, rule["id"], {
                        "box": b["name"], "kind": kind, "stale_min": round(stale_min, 1),
                        "drift_s": b.get("clock_drift_s"), "buffer_rows": b.get("buffer_rows")})
                    if eid:
                        subj = {"offline": f"⚠ EMSBOX {b['name']} offline",
                                "rtc_drift": f"⚠ EMSBOX {b['name']}: drift hodin",
                                "buffer_high": f"⚠ EMSBOX {b['name']}: plný buffer"}[kind]
                        await _send(rule, rule["locality_id"], subj,
                                    f"{subj}\nPoslední heartbeat: {hb}\nDrift: {b.get('clock_drift_s')} s\n"
                                    f"Buffer: {b.get('buffer_rows')} řádků (nejstarší {b.get('buffer_oldest_ts')})")
                else:
                    closed = await _mark_ok(conn, rule["id"], thr)
                    if closed and kind == "offline":
                        rec = (closed["detail"] or {}).get("recovered_rows", 0)
                        await _send(rule, rule["locality_id"], f"✅ EMSBOX {b['name']} zpět online",
                                    f"EMSBOX {b['name']} je zpět online.\n"
                                    f"Výpadek od {closed['opened_at']}.\nDohráno {rec} řádků telemetrie.")
                    elif closed:
                        await _send(rule, rule["locality_id"], f"✅ EMSBOX {b['name']}: {kind} v pořádku",
                                    f"Stav {kind} u boxu {b['name']} se vrátil do normálu.")
                continue

            # scope device / locality → per-modul vyhodnocení (jen kind=offline v MVP)
            if kind != "offline":
                continue
            targets = []
            if scope == "device":
                m = mods.get(rule["target_id"])
                if m:
                    targets = [m]
            else:                                   # locality: všechny zapnuté moduly lokality
                targets = [m for m in mods.values()
                           if m["locality_id"] == rule["locality_id"] and m.get("enabled")]
            bad_names, all_ok = [], True
            for m in targets:
                # POTLAČENÍ BOUŘE: modul za offline boxem přeskoč
                if m.get("emsbox_id") in storm_boxes:
                    all_ok = False                   # neuzavírej během bouře (nevíme)
                    continue
                if m.get("emsbox_id"):
                    hbd = boxes.get(m["emsbox_id"], {}).get("heartbeat_devices")
                    if isinstance(hbd, str):
                        try:
                            hbd = json.loads(hbd)
                        except Exception:
                            hbd = []
                    st = next((d for d in (hbd or []) if str(d.get("device_uid")) == str(m["id"])), None)
                    if st is not None and st.get("ok") is False:
                        bad_names.append(m["name"])
                else:
                    last = await conn.fetchval(
                        "SELECT max(time) FROM samples WHERE device_id = $1 AND time > now() - interval '2 days'",
                        m["id"])
                    stale_min = (_now() - last).total_seconds() / 60 if last else 1e9
                    if stale_min > thr:
                        bad_names.append(m["name"])
            if bad_names:
                await _clear_ok(conn, rule["id"])
                eid = await _open_event(conn, rule["id"], {"devices": bad_names, "kind": "offline"})
                if eid:
                    await _send(rule, rule["locality_id"],
                                f"⚠ Zařízení offline: {', '.join(bad_names)}",
                                f"Zařízení bez dat déle než {thr} min: {', '.join(bad_names)}")
            elif all_ok:
                closed = await _mark_ok(conn, rule["id"], thr)
                if closed:
                    devs = (closed["detail"] or {}).get("devices", [])
                    await _send(rule, rule["locality_id"], "✅ Zařízení zpět online",
                                f"Zařízení opět posílají data: {', '.join(devs) or '—'}")
