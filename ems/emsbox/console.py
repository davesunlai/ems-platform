"""🖥 Servisní konzole boxu: prohlížeč (xterm) ⇄ server ⇄ agent (PTY /bin/sh v kontejneru).

Tok: admin otevře WS /api/emsboxes/{id}/console/ws?token=JWT → server založí session,
zapíše pending_action open_console:<sid> (audit vč. uživatele) → agent si akci vyzvedne
heartbeatem (≤30 s) a připojí se ODCHOZÍM WS na /api/ingest/v1/console/{sid} (box token)
→ server oba konce propojí. Rámce: JSON {"t":"i","d":...} vstup, {"t":"o","d":...} výstup,
{"t":"r","c":sloupce,"r":řádky} resize. Idle timeout 15 min, konec kterékoli strany zavírá obojí.
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

_SESSIONS: dict[str, dict] = {}   # sid -> {"user": ws|None, "agent": ws|None, "box_id": int}
IDLE_S = 900


async def _pump(src: WebSocket, dst_key: str, sess: dict) -> None:
    while True:
        msg = await asyncio.wait_for(src.receive_text(), timeout=IDLE_S)
        dst = sess.get(dst_key)
        if dst is not None:
            await dst.send_text(msg)


@router.websocket("/api/emsboxes/{box_id}/console/ws")
async def console_user(ws: WebSocket, box_id: int, token: str = ""):
    try:
        user = decode_token(token)   # payload: {sub, role, exp}
        role = user.get("role")
        if "admin" not in ROLE_PERMISSIONS.get(role, set()):
            raise ValueError(f"role {role!r} nemá permission admin")
    except Exception as exc:
        logger.warning("konzole box #%s: WS odmítnut: %s", box_id, exc)
        await ws.close(code=4401)
        return
    await ws.accept()
    sid = secrets.token_urlsafe(18)
    sess = _SESSIONS[sid] = {"user": ws, "agent": None, "box_id": box_id}
    username = user.get("sub") or "?"
    ok = await db.set_pending_action(box_id, f"open_console:{sid}", username)
    if not ok:
        await ws.send_text('{"t":"o","d":"box neexistuje\\r\\n"}')
        await ws.close(); _SESSIONS.pop(sid, None); return
    await ws.send_text('{"t":"o","d":"\\u23f3 c\\u030cek\\u00e1m na box (vyzvedne akci heartbeatem, do ~30 s)...\\r\\n"}')
    try:
        for _ in range(70):
            if sess.get("agent") is not None:
                break
            await asyncio.sleep(1)
        if sess.get("agent") is None:
            await ws.send_text('{"t":"o","d":"box se nepripojil (offline?)\\r\\n"}')
            return
        await _pump(ws, "agent", sess)
    except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
        pass
    finally:
        ag = sess.get("agent")
        _SESSIONS.pop(sid, None)
        if ag is not None:
            try:
                await ag.close()
            except Exception:
                pass
        logger.info("konzole box #%s: session %s ukončena (uživatel %s)", box_id, sid[:8], username)


@router.websocket("/api/ingest/v1/console/{sid}")
async def console_agent(ws: WebSocket, sid: str):
    token = ws.headers.get("authorization", "").removeprefix("Bearer ").strip() or ws.query_params.get("token", "")
    box = await db.verify_token(token) if token else None
    sess = _SESSIONS.get(sid)
    if not box or not sess or sess.get("box_id") != box["id"]:
        await ws.close(code=4403)
        return
    await ws.accept()
    sess["agent"] = ws
    user_ws = sess.get("user")
    if user_ws is not None:
        await user_ws.send_text('{"t":"o","d":"\\u2705 box pripojen, otviram shell...\\r\\n"}')
    try:
        await _pump(ws, "user", sess)
    except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
        pass
    finally:
        u = sess.get("user") if _SESSIONS.get(sid) else None
        _SESSIONS.pop(sid, None)
        if u is not None:
            try:
                await u.close()
            except Exception:
                pass
