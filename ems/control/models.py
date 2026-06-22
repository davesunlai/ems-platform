"""Modely povelové roviny (zápis do zařízení)."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class BatteryMode(str, Enum):
    FORCE_CHARGE = "force_charge"        # vynucené nabíjení (ECO_CHARGE)
    FORCE_DISCHARGE = "force_discharge"  # vynucené vybíjení do sítě (ECO_DISCHARGE)
    NORMAL = "normal"                   # normální self-use (GENERAL)


class BatteryModeCommand(BaseModel):
    mode: BatteryMode
    power_pct: int = Field(default=100, ge=1, le=100)     # % výkonu při nabíjení
    target_soc: int = Field(default=100, ge=5, le=100)    # cílový SoC %


class CommandResult(BaseModel):
    ok: bool
    module_id: str
    requested: str
    confirmed_mode: str | None = None
    message: str = ""


# Povely fronty (Solis přes kolektor — jediné Modbus spojení).
SOLIS_ACTIONS = {"force_charge", "force_discharge", "stop", "force_poke", "set_work_mode",
                 "set_charge_current", "set_discharge_current", "set_soc_backup", "set_soc_force",
                 "read_controls", "write_holding", "read_holding"}


class CommandRequest(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)
