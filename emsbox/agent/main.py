"""EMSBOX agent — hlavní smyčky (brief §3, §5).

Spuštění:
    python -m emsbox.agent pair --server https://teraems.com --code A1B2C3D4
    python -m emsbox.agent run

Smyčky: config refresh (300 s, ETag) · poll zařízení (sdílené ems.adapters,
per-device poll_s) · sync (nejnovější napřed, max 1 batch/s, backoff 5 s→5 min
s jitterem) · heartbeat (60 s, per-device stav čtení). Vše přežije offline:
config cache na disku, telemetrie v SQLite bufferu.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from .buffer import Buffer
from .serverlink import ServerLink, load_credentials, save_credentials

logger = logging.getLogger("emsbox")
CONFIG_CACHE = os.environ.get("EMSBOX_CONFIG_CACHE", "/data/config.json")
AGENT_VERSION = "0.1.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_cached_config() -> dict | None:
    p = Path(CONFIG_CACHE)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def _save_config(cfg: dict) -> None:
    p = Path(CONFIG_CACHE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False))


def _build_adapter(dev: dict):
    """Sdílené adaptéry ems.adapters přes stejnou factory jako serverový kolektor.
    transport modbus_tcp/http = beze změny; modbus_rtu přijde v další fázi."""
    from ems.collector.config import build_adapter
    from ems.core.model import Device, DeviceType
    if dev.get("transport") == "modbus_rtu":
        raise NotImplementedError("modbus_rtu transport přijde v další fázi (ModbusSerialClient + port lock)")
    try:
        dtype = DeviceType(dev.get("device_type") or "generation")
    except ValueError:
        dtype = DeviceType.GENERATION
    d = Device(id=dev["device_uid"], name=dev.get("name") or dev["device_uid"],
               type=dtype, adapter=dev["adapter"], params=dict(dev.get("params") or {}))
    return build_adapter(d)


class Agent:
    def __init__(self, cred: dict):
        self.link = ServerLink(cred)
        self.buffer = Buffer(os.environ.get("EMSBOX_BUFFER", "/data/buffer.db"))
        self.cfg: dict = _load_cached_config() or {"devices": [], "settings": {}}
        self.adapters: dict[str, object] = {}
        self.dev_state: dict[str, dict] = {}     # uid -> {last_read_ts, ok, error}
        self.started = time.monotonic()

    # --- config ------------------------------------------------------------
    async def refresh_config(self) -> None:
        try:
            cfg = await self.link.get_config()
        except Exception as exc:
            logger.warning("config pull selhal (jedu z cache): %s", exc)
            return
        if cfg is None:
            return                              # 304
        self.cfg = cfg
        _save_config(cfg)
        await self._reconcile()
        logger.info("config aktualizován: %s zařízení", len(cfg.get("devices", [])))

    async def _reconcile(self) -> None:
        want = {d["device_uid"]: d for d in self.cfg.get("devices", [])}
        for uid in list(self.adapters):
            if uid not in want:
                a = self.adapters.pop(uid)
                try:
                    await a.close()
                except Exception:
                    pass
        for uid, dev in want.items():
            if uid in self.adapters:
                continue
            try:
                a = _build_adapter(dev)
                await a.connect()
                self.adapters[uid] = a
                logger.info("zařízení připojeno: %s (%s/%s)", dev.get("name"), dev["adapter"], dev.get("transport"))
            except Exception as exc:
                self.dev_state[uid] = {"last_read_ts": None, "ok": False, "error": str(exc)}
                logger.warning("připojení %s selhalo (zkusím příště): %s", uid, exc)

    # --- sběr --------------------------------------------------------------
    async def poll_once(self) -> None:
        cycle: list[tuple[str, str, dict]] = []
        for uid, a in list(self.adapters.items()):
            try:
                reading = await a.read()
                metrics = {m.metric.value if hasattr(m.metric, "value") else str(m.metric): m.value
                           for m in (reading.measurements or [])}
                if metrics:
                    ts = _now_iso()
                    cycle.append((uid, ts, metrics))
                    self.dev_state[uid] = {"last_read_ts": ts, "ok": True, "error": None}
            except Exception as exc:
                self.dev_state[uid] = {**self.dev_state.get(uid, {}), "ok": False, "error": str(exc)}
        self.buffer.add_cycle(cycle)

    # --- sync --------------------------------------------------------------
    async def sync_loop(self) -> None:
        backoff = 5.0
        while True:
            batch = self.buffer.next_batch(int(self.cfg.get("settings", {}).get("max_batch_rows", 1000)))
            if not batch:
                await asyncio.sleep(2)
                continue
            try:
                res = await self.link.send_telemetry(batch, _now_iso())
                self.buffer.ack([r["_id"] for r in batch])
                backoff = 5.0
                logger.info("sync: %s řádků (accepted %s, dup %s), buffer %s",
                            len(batch), res.get("accepted"), res.get("duplicates"),
                            self.buffer.stats()["rows"])
                await asyncio.sleep(1.0)         # max 1 batch/s
            except Exception as exc:
                logger.warning("sync selhal (%s) — retry za %.0f s", exc, backoff)
                await asyncio.sleep(backoff + random.uniform(0, backoff / 3))
                backoff = min(backoff * 2, 300.0)

    # --- heartbeat ---------------------------------------------------------
    async def heartbeat_loop(self) -> None:
        while True:
            st = self.buffer.stats()
            disk_free = None
            try:
                import shutil
                disk_free = int(shutil.disk_usage("/data").free / 1e6)
            except Exception:
                pass
            body = {"box_time": _now_iso(), "uptime_s": int(time.monotonic() - self.started),
                    "buffer_rows": st["rows"], "buffer_oldest_ts": st["oldest_ts"],
                    "disk_free_mb": disk_free, "agent_version": AGENT_VERSION,
                    "devices": [{"device_uid": uid, **s} for uid, s in self.dev_state.items()]}
            try:
                await self.link.heartbeat(body)
            except Exception as exc:
                logger.debug("heartbeat selhal: %s", exc)
            await asyncio.sleep(int(self.cfg.get("settings", {}).get("heartbeat_s", 60)))

    async def config_loop(self) -> None:
        while True:
            await self.refresh_config()
            await asyncio.sleep(int(self.cfg.get("settings", {}).get("config_poll_s", 300)))

    async def poll_loop(self) -> None:
        while True:
            t0 = time.monotonic()
            await self.poll_once()
            await asyncio.sleep(max(1.0, 30.0 - (time.monotonic() - t0)))

    async def run(self) -> None:
        await self.refresh_config()
        await self._reconcile()
        await asyncio.gather(self.config_loop(), self.poll_loop(),
                             self.sync_loop(), self.heartbeat_loop())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="emsbox.agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair", help="spárování se serverem (párovací kód z teraems.com)")
    p.add_argument("--server", default=os.environ.get("EMSBOX_SERVER", "https://teraems.com"))
    p.add_argument("--code", required=True)
    sub.add_parser("run", help="hlavní smyčka agenta")
    args = ap.parse_args()

    if args.cmd == "pair":
        import platform
        hw = {"machine": platform.machine(), "system": platform.system(), "node": platform.node()}
        res = asyncio.run(ServerLink.pair(args.server, args.code, hw))
        save_credentials(args.server, res["box_id"], res["box_token"])
        print(f"Spárováno: box_id={res['box_id']} (credentials uloženy)")
        return

    cred = load_credentials()
    if not cred:
        raise SystemExit("Box není spárovaný — nejdřív: python -m emsbox.agent pair --code XXXXXXXX")
    asyncio.run(Agent(cred).run())


if __name__ == "__main__":
    main()
