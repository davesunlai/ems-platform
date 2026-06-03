"""FastAPI závislosti pro autentizaci a kontrolu oprávnění."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import ROLE_PERMISSIONS
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chybí token")
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Neplatný token")
    role = payload.get("role", "")
    return {
        "username": payload.get("sub"),
        "role": role,
        "permissions": ROLE_PERMISSIONS.get(role, set()),
    }


def require_permission(permission: str):
    async def dependency(user: dict = Depends(get_current_user)) -> dict:
        if permission not in user["permissions"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Chybí oprávnění '{permission}'",
            )
        return user
    return dependency
