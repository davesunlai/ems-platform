"""Box-token autentizace pro ingest — nezávislá na uživatelském JWT."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import db

_bearer = HTTPBearer(auto_error=False)


async def box_auth(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if cred is None or not cred.credentials:
        raise HTTPException(status_code=401, detail="chybí box token")
    box = await db.verify_token(cred.credentials)
    if not box:
        raise HTTPException(status_code=401, detail="neplatný box token")
    return box
