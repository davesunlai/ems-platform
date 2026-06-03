#!/usr/bin/env python3
"""Vypíše VŠECHNY sensory reálného Goodwe měniče.

Slouží k ověření a doladění mapování (ems/adapters/goodwe/mapping.py)
proti konkrétnímu kusu HW. Spusť po zprovoznění VPN:

    python scripts/discover.py 192.168.1.10
    python scripts/discover.py 192.168.1.10 --port 502   # Modbus TCP

Výstup: id sensoru | název | hodnota | jednotka. Sensor ID, které vidíš
zde, patří do kandidátních seznamů v mapping.py.
"""
from __future__ import annotations

import argparse
import asyncio


async def main(host: str, port: int) -> None:
    import goodwe

    inverter = await goodwe.connect(host, port=port)
    print(f"# model={getattr(inverter, 'model_name', '?')} "
          f"sériové={getattr(inverter, 'serial_number', '?')}\n")
    data = await inverter.read_runtime_data()
    width = max((len(s.id_) for s in inverter.sensors()), default=20)
    for sensor in inverter.sensors():
        if sensor.id_ in data:
            print(f"{sensor.id_:<{width}}  {sensor.name:<32}  {data[sensor.id_]} {sensor.unit}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("host", help="IP adresa měniče")
    ap.add_argument("--port", type=int, default=8899, help="8899 (UDP) nebo 502 (Modbus TCP)")
    args = ap.parse_args()
    asyncio.run(main(args.host, args.port))
