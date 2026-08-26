"""Adaptér pro tepelné čerpadlo Stiebel Eltron přes bránu ISG (Modbus TCP).

Mapa registrů OVĚŘENA sweepem 26. 8. 2026 na kuse (WPM3, ne 3i) — viz
docs/STIEBEL-ISG-BRIEF.md §OVĚŘENO. Klíčové odchylky od dokumentace:

  * Energetický pár doc-3501/3511 („TUV dnes") je na tomto kuse TOPENÍ
    (ověřeno proti displeji „VD TOPENÍ DEN"); pár 3504/3514 je TUV (zde 0,
    TČ TUV nedělá — TUV řeší nádrže + spirála).
  * Čítače *_total (3502/3503/3505/3506/3512/3513/3515/3516) vracejí 0
    (známý nespolehlivý 35xx FW) → čtou se, ale denní agregace jede z *_today.
  * Runtime registry 3517+ NEEXISTUJÍ (IllegalAddress) → runtime výhradně
    z hp_runs edge detektoru.
  * WPM3: 512/513/515/520/521/522/536/538/539/540 = N/A → nečteme.
  * Blok 1502–1510 vrací nesmysly → čteme jen 1501 (režim) + 5001 (SG).

Adresy v dokumentaci ISG jsou 1-based → pymodbus addr = doc − 1.
Sentinel 0x8000 (S16 −32768) = N/A → None. Jen čtení. Poll 30 s.
"""
from __future__ import annotations

import asyncio
import logging
import time

from ems.core.model import Measurement, Metric, Reading, UNIT_OF

logger = logging.getLogger(__name__)

_NA = -32768        # 0x8000 jako S16
_INVALID = 32767    # 0x7FFF


def _s16(v: int) -> int:
    return v - 0x10000 if v >= 0x8000 else v


def _val(v: int, scale: float = 1.0) -> float | None:
    s = _s16(v)
    if s in (_NA, _INVALID):
        return None
    return s * scale


class StiebelIsgAdapter:
    """Jen čtení: teploty, stav, denní energie. Drží jedno Modbus TCP spojení."""

    def __init__(self, device_id: str, host: str, port: int = 502, unit: int = 1,
                 hp_nominal_kw: float = 3.5, nhz_kw: float = 0.0,
                 poll_s: float = 30.0, timeout: float = 3.0, **_ignored):
        self.device_id = device_id
        self.host, self.port, self.unit = host, int(port), int(unit)
        self.hp_nominal_kw = float(hp_nominal_kw)
        self.nhz_kw = float(nhz_kw)
        self.poll_s = float(poll_s)
        self.timeout = float(timeout)
        self._client = None
        self._last_poll = 0.0
        self._last: dict | None = None   # poslední úspěšný snapshot (pro hp_telemetry)

    # --- Modbus ---------------------------------------------------------
    def _ensure_client(self):
        from pymodbus.client import ModbusTcpClient
        if self._client is None:
            self._client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout)
        if not self._client.connected:
            self._client.connect()
        return self._client

    def _read_block(self, doc_start: int, count: int, fc: int = 4) -> list[int] | None:
        c = self._ensure_client()
        fn = c.read_input_registers if fc == 4 else c.read_holding_registers
        r = fn(doc_start - 1, count=count, device_id=self.unit)
        if r is None or r.isError():
            return None
        return list(r.registers)

    def _fetch(self) -> dict:
        """Synchronní čtení všech bloků (volané přes to_thread)."""
        out: dict = {}
        b1 = self._read_block(507, 13)          # doc 507..519
        if b1:
            out["t_outdoor"] = _val(b1[0], 0.1)          # 507
            out["t_hc1"] = _val(b1[1], 0.1)              # 508 = „SKUT TEPLOTA AKUMULACE" na displeji
            out["t_buffer"] = _val(b1[10], 0.1)          # 517
            out["t_buffer_set"] = _val(b1[11], 0.1)      # 518
            out["p_heating"] = _val(b1[12], 0.01)        # 519
        st = self._read_block(2501, 7)          # doc 2501..2507
        if st:
            s = st[0] & 0xFFFF
            out["status_raw"] = s
            out["compressor_on"] = bool(s & 64)
            out["mode_heating"] = bool(s & 16)
            out["mode_dhw"] = bool(s & 32)
            out["nhz_on"] = bool(s & 8)
            out["defrost"] = bool(s & 512)
            out["evu_blocked"] = bool(_s16(st[1]))       # 2502
            out["fault"] = bool(_s16(st[3]))             # 2504
            out["error_code"] = _s16(st[6])              # 2507
        en = self._read_block(3501, 16)         # doc 3501..3516
        if en:
            # OVĚŘENO: pár „TUV" v doc = na tomto kuse TOPENÍ (a naopak) — viz docstring.
            out["heat_heating_today_kwh"] = _val(en[0])   # doc 3501
            out["heat_dhw_today_kwh"] = _val(en[3])       # doc 3504
            out["el_heating_today_kwh"] = _val(en[10])    # doc 3511
            out["el_dhw_today_kwh"] = _val(en[13])        # doc 3514
            def tot(k_kwh, k_mwh):
                a, b = _val(en[k_kwh]), _val(en[k_mwh])
                return None if a is None or b is None else a + 1000 * b
            out["heat_heating_total_kwh"] = tot(1, 2)     # 3502+3503 (FW: zatím 0)
            out["heat_dhw_total_kwh"] = tot(4, 5)         # 3505+3506
            out["el_heating_total_kwh"] = tot(11, 12)     # 3512+3513
            out["el_dhw_total_kwh"] = tot(14, 15)         # 3515+3516
        m = self._read_block(1501, 1, fc=3)
        if m:
            out["operating_mode"] = _s16(m[0])
        sg = self._read_block(5001, 1)
        if sg:
            out["sg_state"] = _s16(sg[0])
        return out

    # --- kanonický výstup ----------------------------------------------
    @staticmethod
    def _hp_mode(d: dict) -> str:
        if d.get("defrost"):
            return "defrost"
        if d.get("compressor_on") and d.get("mode_dhw"):
            return "dhw"
        if d.get("compressor_on"):
            return "heating"
        return "idle"

    def _power_est_w(self, d: dict) -> float:
        p = self.hp_nominal_kw * 1000 if d.get("compressor_on") else 0.0
        if d.get("nhz_on"):
            p += self.nhz_kw * 1000
        return p

    async def read(self) -> Reading:
        now = time.monotonic()
        if now - self._last_poll < self.poll_s:
            return Reading(device_id=self.device_id, measurements=[])
        self._last_poll = now
        try:
            d = await asyncio.to_thread(self._fetch)
        except Exception as exc:
            logger.warning("Stiebel ISG %s: čtení selhalo: %s", self.host, exc)
            try:
                if self._client:
                    self._client.close()
            finally:
                self._client = None
            return Reading(device_id=self.device_id, measurements=[])
        if not d:
            return Reading(device_id=self.device_id, measurements=[])
        d["hp_mode"] = self._hp_mode(d)
        d["power_est_w"] = self._power_est_w(d)
        self._last = d

        ms: list[Measurement] = []

        def add(metric: Metric, key: str, scale: float = 1.0):
            v = d.get(key)
            if v is not None:
                ms.append(Measurement(metric=metric, value=float(v) * scale,
                                      unit=UNIT_OF[metric]))
        add(Metric.HP_T_OUTDOOR, "t_outdoor")
        add(Metric.HP_T_TANK, "t_hc1")
        add(Metric.HP_T_BUFFER, "t_buffer")
        add(Metric.HP_T_BUFFER_SET, "t_buffer_set")
        add(Metric.HP_PRESSURE, "p_heating")
        add(Metric.HP_POWER_EST, "power_est_w")
        add(Metric.HP_EL_HEATING_TODAY, "el_heating_today_kwh")
        add(Metric.HP_EL_DHW_TODAY, "el_dhw_today_kwh")
        add(Metric.HP_HEAT_HEATING_TODAY, "heat_heating_today_kwh")
        add(Metric.HP_HEAT_DHW_TODAY, "heat_dhw_today_kwh")
        ms.append(Measurement(metric=Metric.HP_COMPRESSOR, value=1.0 if d.get("compressor_on") else 0.0,
                              unit=UNIT_OF[Metric.HP_COMPRESSOR]))
        ms.append(Measurement(metric=Metric.HP_FAULT,
                              value=1.0 if (d.get("fault") or (d.get("error_code") or 0) != 0) else 0.0,
                              unit=UNIT_OF[Metric.HP_FAULT]))
        states = {"hp_mode": d["hp_mode"], "operating_mode": str(d.get("operating_mode")),
                  "sg_state": str(d.get("sg_state"))}
        return Reading(device_id=self.device_id, measurements=ms, states=states)
