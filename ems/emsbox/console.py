"""🖥 Servisní konzole boxu: prohlížeč (xterm) ⇄ server ⇄ agent (PTY /bin/sh v kontejneru).

Model (v0.82.5 — robustní): každá session má dvě fronty (do uživatele / do agenta) a čeká,
až se sejdou OBĚ strany (event `ready`). Teprve pak běží obousměrné přeposílání. Konec kterékoli
strany zvedne `closing`, druhá smyčka se ukončí čistě a obě WS se zavřou jednou. Žádné vzájemné
zavírání v finally hned po připojení (to působilo okamžitý ConnectionClosedError / 1006).
"""
from __future__ import annotations

import asyncio
import logging
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ems.auth.models import ROLE_PERMISSIONS
from ems.auth.security import decode_token
from . import db

logger = logging.getLogger("ems.console")
router = APIRouter()

_SESSIONS: dict[str, "Session"] = {}
IDLE_S = 900
WAIT_PEER_S = 75


class Session:
    def __init__(self, box_id: int, username: str):
        self.box_id = box_id
        self.username = username
        self.user_ws: WebSocket | None = None
        self.agent_ws: WebSocket | None = None
        self.ready = asyncio.Event()      # obě strany připojeny
        self.closing = asyncio.Event()

    def both(self) -> bool:
        return self.user_ws is not None and self.agent_ws is not None


async def _relay(src: WebSocket, dst: WebSocket, sess: Session) -> None:
    """Přeposílá text z src do dst, dokud jedna strana nespadne / nezvedne closing."""
    try:
        while not sess.closing.is_set():
            try:
                msg = await asyncio.wait_for(src.receive_text(), timeout=IDLE_S)
            except asyncio.TimeoutError:
                break
            try:
                await dst.send_text(msg)
            except Exception:
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sess.closing.set()


@router.websocket("/api/emsboxes/{box_id}/console/ws")
async def console_user(ws: WebSocket, box_id: int, token: str = ""):
    try:
        user = decode_token(token)
        role = user.get("role")
        if "admin" not in ROLE_PERMISSIONS.get(role, set()):
            raise ValueError(f"role {role!r} nemá admin")
    except Exception as exc:
        logger.warning("konzole box #%s: WS uživatele odmítnut: %s", box_id, exc)
        await ws.close(code=4401)
        return
    await ws.accept()
    sid = secrets.token_urlsafe(18)
    username = user.get("sub") or "?"
    sess = _SESSIONS[sid] = Session(box_id, username)
    sess.user_ws = ws
    ok = await db.set_pending_action(box_id, f"open_console:{sid}", username)
    if not ok:
        await ws.send_text('{"t":"o","d":"box neexistuje\\r\\n"}')
        await ws.close(); _SESSIONS.pop(sid, None); return
    await ws.send_text('{"t":"o","d":"\\u23f3 c\\u030cek\\u00e1m na box (vyzvedne akci heartbeatem, do ~30 s)...\\r\\n"}')
    logger.info("konzole box #%s: session %s… otevřena uživatelem %s", box_id, sid[:8], username)
    try:
        try:
            await asyncio.wait_for(sess.ready.wait(), timeout=WAIT_PEER_S)
        except asyncio.TimeoutError:
            await ws.send_text('{"t":"o","d":"box se nepripojil (offline?)\\r\\n"}')
            return
        await ws.send_text('{"t":"o","d":"\\u2705 box pripojen, otvi\\u0301ram shell...\\r\\n"}')
        await _relay(ws, sess.agent_ws, sess)   # uživatel → agent
    except (WebSocketDisconnect, RuntimeError):
        sess.closing.set()
    finally:
        await _teardown(sid)


@router.websocket("/api/ingest/v1/console/{sid}")
async def console_agent(ws: WebSocket, sid: str):
    token = ws.headers.get("authorization", "").removeprefix("Bearer ").strip() or ws.query_params.get("token", "")
    box = await db.verify_token(token) if token else None
    sess = _SESSIONS.get(sid)
    if not box or not sess or sess.box_id != box["id"]:
        logger.warning("konzole: agent WS odmítnut (sid %s, box_ok=%s, sess=%s)", sid[:8], bool(box), sess is not None)
        await ws.close(code=4403)
        return
    await ws.accept()
    sess.agent_ws = ws
    if sess.both():
        sess.ready.set()
    logger.info("konzole box #%s: agent připojen k session %s…", sess.box_id, sid[:8])
    try:
        await _relay(ws, sess.user_ws, sess)    # agent → uživatel
    except (WebSocketDisconnect, RuntimeError):
        sess.closing.set()
    finally:
        await _teardown(sid)


async def _teardown(sid: str) -> None:
    sess = _SESSIONS.pop(sid, None)
    if not sess:
        return
    sess.closing.set()
    for w in (sess.user_ws, sess.agent_ws):
        if w is not None:
            try:
                await w.close()
            except Exception:
                pass
    logger.info("konzole box #%s: session %s… uzavřena", sess.box_id, sid[:8])
