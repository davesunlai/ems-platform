"""Vlastní ikonky schématu ze schránky: upload (admin) → Pillow zmenší na 64×64 (zachová poměr,
průhledné doplnění), uloží jako WebP q80 (typicky 1–3 kB) do tabulky ui_icons; servírováno
GET /api/ui-icons/{id} s dlouhou cache. Cesta '/api/ui-icons/<id>' funguje v <image href> stejně
jako vestavěná /flow-icons/*.svg."""
from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from ems.api.db import get_pool
from ems.auth.deps import require_permission

router = APIRouter()
SIZE = 64
MAX_UPLOAD = 8 * 1024 * 1024


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS ui_icons (
                 id BIGSERIAL PRIMARY KEY,
                 element TEXT NOT NULL,
                 name TEXT,
                 mime TEXT NOT NULL DEFAULT 'image/webp',
                 data BYTEA NOT NULL,
                 bytes INT NOT NULL,
                 created_by TEXT,
                 created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")


def _convert(raw: bytes) -> bytes:
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im).convert("RGBA")
    # ořez průhledných / jednobarevných okrajů (print screen bývá s okrajem)
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    im.thumbnail((SIZE, SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2), im)
    out = io.BytesIO()
    canvas.save(out, "WEBP", quality=80, method=6)
    return out.getvalue()


@router.post("/api/ui-icons")
async def upload_icon(element: str, file: UploadFile = File(...),
                      user: dict = Depends(require_permission("admin"))):
    raw = await file.read()
    if not raw or len(raw) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="prázdný nebo příliš velký obrázek (max 8 MB)")
    try:
        data = _convert(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"obrázek nejde zpracovat: {exc}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        iid = await conn.fetchval(
            "INSERT INTO ui_icons (element, name, mime, data, bytes, created_by) VALUES ($1,$2,'image/webp',$3,$4,$5) RETURNING id",
            element, file.filename or "schránka", data, len(data), user.get("username"))
    return {"id": iid, "url": f"/api/ui-icons/{iid}", "bytes": len(data), "element": element}


@router.get("/api/ui-icons")
async def list_icons(element: str | None = None, _: dict = Depends(require_permission("read"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, element, name, bytes, created_by, created_at FROM ui_icons "
            + ("WHERE element=$1 " if element else "") + "ORDER BY id", *([element] if element else []))
    return [{"id": r["id"], "url": f"/api/ui-icons/{r['id']}", "element": r["element"], "name": r["name"],
             "bytes": r["bytes"], "by": r["created_by"]} for r in rows]


@router.get("/api/ui-icons/{icon_id}")
async def get_icon(icon_id: int):
    """Veřejné (ikonka není tajemství) — <image href> neposílá Authorization hlavičku."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT mime, data FROM ui_icons WHERE id=$1", icon_id)
    if not r:
        raise HTTPException(status_code=404)
    return Response(content=bytes(r["data"]), media_type=r["mime"],
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.delete("/api/ui-icons/{icon_id}", status_code=204)
async def delete_icon(icon_id: int, _: dict = Depends(require_permission("admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ui_icons WHERE id=$1", icon_id)
