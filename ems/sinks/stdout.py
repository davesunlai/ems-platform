"""Sink, který vzorky jen vypíše na stdout. Bez závislostí — pro první běh."""
from __future__ import annotations

from ems.core.model import Sample


class StdoutSink:
    async def write(self, samples: list[Sample]) -> None:
        if not samples:
            return
        ts = samples[0].time.isoformat(timespec="seconds")
        dev = samples[0].device_id
        parts = [f"{s.metric.value}={s.value}{s.unit}" for s in samples]
        print(f"[{ts}] {dev}: " + "  ".join(parts), flush=True)

    async def write_states(self, device_id: str, states: dict) -> None:
        if states:
            parts = [f"{k}={v}" for k, v in states.items()]
            print(f"  [{device_id}] stav: " + "  ".join(parts), flush=True)

    async def close(self) -> None:
        return None
