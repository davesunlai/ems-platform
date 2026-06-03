"""Kontrakty modulární vrstvy.

Adaptér = překlad nativního protokolu zařízení -> kanonický Reading.
Sink     = zápis kanonických Sample kamkoliv (stdout, TimescaleDB, později bus).

Jádro zná jen tyto dva protokoly. Přidat nový typ zdroje = napsat nový
adaptér; přidat nové úložiště = napsat nový sink. Nic v jádře se nemění.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import Reading, Sample


@runtime_checkable
class TelemetryAdapter(Protocol):
    device_id: str

    async def connect(self) -> None: ...

    async def read(self) -> Reading: ...

    async def close(self) -> None: ...


@runtime_checkable
class Sink(Protocol):
    async def write(self, samples: list[Sample]) -> None: ...

    async def close(self) -> None: ...
