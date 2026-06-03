"""Sink zapisující vzorky do TimescaleDB (PostgreSQL + hypertable).

Schéma vytváří infra/timescaledb/init.sql. Tabulka `samples` je hypertable
particionovaná podle času.
"""
from __future__ import annotations

import logging

from ems.core.model import Sample

logger = logging.getLogger(__name__)


class TimescaleSink:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool = None

    async def _ensure_pool(self):
        if self._pool is None:
            import asyncpg  # lazy import
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=4)
            logger.info("TimescaleSink: pool připojen")
        return self._pool

    async def write(self, samples: list[Sample]) -> None:
        if not samples:
            return
        pool = await self._ensure_pool()
        rows = [
            (s.time, s.device_id, s.metric.value, s.value, s.unit, s.quality.value)
            for s in samples
        ]
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO samples (time, device_id, metric, value, unit, quality)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                rows,
            )

    async def write_states(self, device_id: str, states: dict) -> None:
        if not states:
            return
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_state (
                    device_id  TEXT NOT NULL,
                    key        TEXT NOT NULL,
                    value      TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (device_id, key)
                )
                """
            )
            for key, value in states.items():
                await conn.execute(
                    """
                    INSERT INTO device_state (device_id, key, value, updated_at)
                    VALUES ($1, $2, $3, now())
                    ON CONFLICT (device_id, key)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                    """,
                    device_id, key, str(value),
                )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
