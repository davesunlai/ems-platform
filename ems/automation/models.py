"""Modely automatizačních pravidel (logické moduly)."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RuleType(str, Enum):
    SPOT_CHARGE = "spot_charge"        # nabíjej při nízké spotové ceně
    SPOT_DISCHARGE = "spot_discharge"  # vybíjej do sítě při vysoké ceně


class SpotChargeParams(BaseModel):
    target_module: str                       # id řiditelného (goodwe) modulu
    price_threshold: float                   # Kč/MWh — pod tím nabíjet
    soc_max: int = Field(default=95, ge=5, le=100)     # nenabíjet nad tento SoC
    charge_power: int = Field(default=100, ge=1, le=100)


class RuleCreate(BaseModel):
    id: str
    type: RuleType = RuleType.SPOT_CHARGE
    enabled: bool = True
    params: dict = Field(default_factory=dict)


class RuleUpdate(BaseModel):
    enabled: bool | None = None
    params: dict | None = None


class Rule(BaseModel):
    id: str
    type: str
    enabled: bool
    params: dict
    last_decision: str | None = None
    last_action: str | None = None
    last_action_at: str | None = None
    last_eval_at: str | None = None
