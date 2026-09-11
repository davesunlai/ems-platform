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


def _remove_bg(im, tol: int):
    """Průhledné pozadí: barva = medián rohů; od okrajů flood-fill přes pixely v toleranci → alpha 0.
    Vnitřní plochy stejné barvy (odříznuté od okraje kresbou) zůstávají — přesně jako kouzelná hůlka."""
    from collections import deque
    w, h = im.size
    px = im.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    bg = tuple(sorted(c[i] for c in corners)[1] for i in range(3))   # medián po kanálech (odolné proti kurzoru v rohu)
    def near(p):
        return p[3] == 0 or (abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2])) <= tol * 3
    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if near(px[x, y]):
                q.append((x, y)); seen[y * w + x] = 1
    for y in range(h):
        for x in (0, w - 1):
            if not seen[y * w + x] and near(px[x, y]):
                q.append((x, y)); seen[y * w + x] = 1
    while q:
        x, y = q.popleft()
        r, g, b, _ = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and near(px[nx, ny]):
                seen[ny * w + nx] = 1
                q.append((nx, ny))
    return im


def _convert(raw: bytes, transparent: bool = True, tol: int = 40) -> bytes:
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im).convert("RGBA")
    if max(im.size) > 320:                    # flood-fill v Pythonu: nejdřív zmenšit (print screeny bývají velké)
        im.thumbnail((320, 320), Image.LANCZOS)
    if transparent:
        im = _remove_bg(im, max(0, min(120, tol)))
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
async def upload_icon(element: str, file: UploadFile = File(...), transparent: bool = True, tol: int = 40,
                      user: dict = Depends(require_permission("admin"))):
    raw = await file.read()
    if not raw or len(raw) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="prázdný nebo příliš velký obrázek (max 8 MB)")
    try:
        data = _convert(raw, transparent=transparent, tol=tol)
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
