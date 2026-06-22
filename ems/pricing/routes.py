"""API cenového modelu: versionovaný tarif lokality + stav kurzu ČNB."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ems.auth.deps import require_permission
from . import db as pdb

router = APIRouter(prefix="/api/pricing", tags=["pricing"])
read = require_permission("read")
admin = require_permission("admin")


class TariffIn(BaseModel):
    valid_from: date | None = None
    mode: str = "spot"                 # spot | fixed
    monthly_fee: float = 0
    two_tariff: bool = False
    nt_hours: str = ""                 # CSV hodin 0-23
    spot_buy_surcharge: float = 0
    spot_sell_fee: float = 200
    dist_buy_vt: float = 0
    dist_buy_nt: float = 0
    levies: float = 0
    fix_buy_vt: float = 0
    fix_buy_nt: float = 0
    fix_sell: float = 0
    fx_source: str = "cnb"
    fx_eur_czk: float | None = None


@router.get("/fx")
async def get_fx(_: dict = Depends(read)):
    return {"fx": await pdb.latest_fx()}


@router.get("/{locality_id}/tariff")
async def get_tariff(locality_id: int, _: dict = Depends(read)):
    return {
        "effective": await pdb.get_effective(locality_id),
        "versions": await pdb.list_versions(locality_id),
        "fx": await pdb.latest_fx(),
    }


@router.post("/{locality_id}/tariff")
async def add_tariff(locality_id: int, body: TariffIn, _: dict = Depends(admin)):
    vf = body.valid_from or date.today()
    fields = body.model_dump(exclude={"valid_from"})
    row = await pdb.add_version(locality_id, vf, fields)
    return {"version": row}


@router.delete("/tariff/{version_id}")
async def del_tariff(version_id: int, _: dict = Depends(admin)):
    await pdb.delete_version(version_id)
    return {"ok": True}
