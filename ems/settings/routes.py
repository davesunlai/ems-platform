"""Globální nastavení aplikace – zatím globální vzhled (motiv) nastavitelný adminem."""
from fastapi import APIRouter, Depends

from ems.api.db import get_setting, set_setting
from ems.auth.deps import require_permission

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/global-theme")
async def get_global_theme(_: dict = Depends(require_permission("read"))):
    """Globální výchozí vzhled (pro uživatele bez vlastního). Prázdné = není nastaveno."""
    return await get_setting("global_theme", {}) or {}


@router.put("/global-theme")
async def set_global_theme(body: dict, _: dict = Depends(require_permission("admin"))):
    """Nastaví globální vzhled. Body: {theme, custom, saved, ui_style}. Jen admin."""
    await set_setting("global_theme", body or {})
    return {"ok": True}
