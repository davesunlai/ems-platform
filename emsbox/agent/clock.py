"""Hodiny EMSBOXu (RPi bez RTC) — brief v1.3.0.

Po výpadku proudu naběhne RPi s časem z posledního uložení (fake-hwclock), čte se špatným
časem a teprve po NTP synchronizaci skočí na správný. Incident 25. 10. 2026: vzorky 6:08–13:14
zapsané jako 3:02–10:00 (posun −3 h 06).

Obrana:
1. `synced()` — stav kernelových hodin přes adjtimex (STA_UNSYNC): NTP daemon na hostu ho nastaví,
   funguje i z kontejneru (hodiny jsou sdílené).
2. Každý vzorek nese monotonic čas + boot_id. Při odeslání (až po synchronizaci) se timestamp
   přepočítá: ts = now_wall − (mono_now − mono_sample). Skok wall-clocku tak vzorky nerozhodí,
   pokud mezitím nebyl reboot (boot_id). Vzorky z doby před rebootem už opravit nelze — ty se pošlou
   tak, jak jsou, jen pokud byly pořízené se synchronizovanými hodinami (flag v řádku), jinak se zahodí.
"""
from __future__ import annotations

import ctypes
import logging
import time

logger = logging.getLogger("emsbox.clock")

STA_UNSYNC = 0x0040


class _Timex(ctypes.Structure):
    _fields_ = [("modes", ctypes.c_uint), ("offset", ctypes.c_long), ("freq", ctypes.c_long),
                ("maxerror", ctypes.c_long), ("esterror", ctypes.c_long), ("status", ctypes.c_int),
                ("constant", ctypes.c_long), ("precision", ctypes.c_long), ("tolerance", ctypes.c_long),
                ("time", ctypes.c_long * 2), ("tick", ctypes.c_long), ("ppsfreq", ctypes.c_long),
                ("jitter", ctypes.c_long), ("shift", ctypes.c_int), ("stabil", ctypes.c_long),
                ("jitcnt", ctypes.c_long), ("calcnt", ctypes.c_long), ("errcnt", ctypes.c_long),
                ("stbcnt", ctypes.c_long), ("tai", ctypes.c_int), ("_pad", ctypes.c_int * 11)]


def synced() -> bool | None:
    """True = kernel hlásí synchronizované hodiny, False = STA_UNSYNC, None = nelze zjistit."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        tx = _Timex()
        tx.modes = 0
        rc = libc.adjtimex(ctypes.byref(tx))
        if rc < 0:
            return None
        return not (tx.status & STA_UNSYNC)
    except Exception as exc:
        logger.debug("adjtimex: %s", exc)
        return None


def boot_id() -> str:
    try:
        return open("/proc/sys/kernel/random/boot_id").read().strip()
    except Exception:
        return ""


def corrected_ts(sample_wall_iso: str, sample_mono: float | None, sample_boot: str | None) -> tuple[str, bool]:
    """Vrátí (ts_iso, opraveno). Oprava jen když boot_id sedí a wall−mono vztah se od pořízení
    posunul o > 5 s (= skok hodin po NTP)."""
    from datetime import datetime, timezone
    if sample_mono is None or not sample_boot or sample_boot != boot_id():
        return sample_wall_iso, False
    try:
        wall_now = time.time()
        mono_now = time.monotonic()
        sample_wall = datetime.fromisoformat(sample_wall_iso.replace("Z", "+00:00")).timestamp()
        expected_wall = wall_now - (mono_now - sample_mono)
        if abs(expected_wall - sample_wall) <= 5.0:
            return sample_wall_iso, False
        fixed = datetime.fromtimestamp(expected_wall, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return fixed, True
    except Exception:
        return sample_wall_iso, False
