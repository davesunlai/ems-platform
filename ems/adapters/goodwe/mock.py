"""Mock adaptér: simulovaný hybridní měnič (FVE + baterie + odběr).

Umožní rozjet celý stack ještě před zprovozněním VPN k reálnému měniči.
Generuje realistickou denní křivku FVE, odběr a chování baterie.
V configu pak stačí přepnout adapter: mock -> goodwe a nic dalšího se nemění.
"""
from __future__ import annotations

import math
import random

from ems.core.model import Measurement, Metric, Reading, UNIT_OF, utcnow


class MockInverterAdapter:
    def __init__(
        self,
        device_id: str,
        pv_peak_w: float = 26000.0,
        battery_capacity_kwh: float = 52.0,
        initial_soc: float = 55.0,
    ) -> None:
        self.device_id = device_id
        self.pv_peak_w = pv_peak_w
        self.battery_capacity_kwh = battery_capacity_kwh
        self._soc = initial_soc

    async def connect(self) -> None:
        return None

    async def read(self) -> Reading:
        now = utcnow()
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0

        # denní zvonovitá křivka FVE: 0 v 6h a 18h, max kolem poledne
        sun = max(0.0, math.sin((hour - 6.0) / 12.0 * math.pi))
        pv = round(self.pv_peak_w * sun * (0.85 + 0.1 * random.random()), 1)

        # odběr domácnosti: základ + mírné kolísání
        load = round(700.0 + 1800.0 * abs(math.sin(hour / 24.0 * 2 * math.pi)) + 200.0 * random.random(), 1)

        # baterie: přebytek FVE nabíjí (+), nedostatek vybíjí (-)
        net = pv - load
        battery = round(net * 0.6, 1)  # + nabíjení / - vybíjení
        # nedopustit nabíjení nad 100 % / vybíjení pod 5 %
        if battery > 0 and self._soc >= 100.0:
            battery = 0.0
        if battery < 0 and self._soc <= 5.0:
            battery = 0.0

        # zbytek dorovná síť: + import / - export
        grid = round(-(net - battery), 1)

        # naivní integrace SoC (krok je orientační, ne fyzikálně přesný)
        self._soc = min(100.0, max(5.0, self._soc + battery / (self.battery_capacity_kwh * 1000.0) * 0.5))

        freq = round(49.98 + 0.04 * random.random(), 3)
        temp = round(28.0 + 8.0 * sun + random.random(), 1)

        m = lambda metric, value: Measurement(metric=metric, value=value, unit=UNIT_OF[metric])
        return Reading(
            device_id=self.device_id,
            timestamp=now,
            measurements=[
                m(Metric.PV_POWER, pv),
                m(Metric.LOAD_POWER, load),
                m(Metric.BATTERY_POWER, battery),
                m(Metric.BATTERY_SOC, round(self._soc, 1)),
                m(Metric.GRID_POWER, grid),
                m(Metric.FREQUENCY, freq),
                m(Metric.TEMPERATURE, temp),
            ],
        )

    async def close(self) -> None:
        return None
