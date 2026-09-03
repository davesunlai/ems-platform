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
    # modbus_rtu: transport_params nesou serial_port/baudrate/... — adaptér při
    # serial_port automaticky použije ModbusSerialClient. Přístup na port serializuje
    # agentní _io_lock (jeden master na sběrnici; víc zařízení na jednom portu = další fáze).
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
        self.online = False
        self.last_sync_ts: str | None = None
        self._io_lock = asyncio.Lock()      # serializace čtení × povelů na sdíleném Modbus spojení

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
                self.dev_state.pop(uid, None)
                logger.info("zařízení připojeno: %s (%s/%s)", dev.get("name"), dev["adapter"], dev.get("transport"))
            except Exception as exc:
                self.dev_state[uid] = {"last_read_ts": None, "ok": False, "error": str(exc)}
                logger.warning("připojení %s selhalo (retry za config tick): %s", uid, exc)

    # --- sběr --------------------------------------------------------------
    async def poll_once(self) -> None:
        cycle: list[tuple[str, str, dict]] = []
        for uid, a in list(self.adapters.items()):
            try:
                async with self._io_lock:
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
                self.last_sync_ts = _now_iso()
                self.online = True
                logger.info("sync: %s řádků (accepted %s, dup %s), buffer %s",
                            len(batch), res.get("accepted"), res.get("duplicates"),
                            self.buffer.stats()["rows"])
                await asyncio.sleep(1.0)         # max 1 batch/s
            except Exception as exc:
                self.online = False
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
                    "private_ip": _private_ip(), **_sysinfo(),
                    "buffer_rows": st["rows"], "buffer_oldest_ts": st["oldest_ts"],
                    "disk_free_mb": disk_free, "agent_version": AGENT_VERSION,
                    "devices": [{"device_uid": uid, **s} for uid, s in self.dev_state.items()]}
            try:
                await self.link.heartbeat(body)
                self.online = True
            except Exception as exc:
                self.online = False
                logger.debug("heartbeat selhal: %s", exc)
            await asyncio.sleep(int(self.cfg.get("settings", {}).get("heartbeat_s", 60)))

    async def command_loop(self) -> None:
        """Povelový kanál (varianta B): povely planneru/ruční vykonává BOX —
        na střídači je jediný Modbus klient. Poll à 5 s, výsledek hned zpět."""
        from ems.control.dispatch import dispatch_command
        while True:
            await asyncio.sleep(5)
            try:
                cmds, cfg_etag = await self.link.get_commands()
            except Exception:
                continue
            # změna configu na serveru? (přiřazení/odebrání zařízení) → stáhni HNED, nečekej na 5min poll
            if cfg_etag and cfg_etag != getattr(self.link, "_config_etag", None):
                await self.refresh_config()
                await self._reconcile()
            for c in cmds:
                a = self.adapters.get(c["module_id"])
                if a is None:
                    try:
                        await self.link.send_command_result(c, False, {"error": "zařízení není na boxu připojeno"})
                    except Exception:
                        pass
                    continue
                try:
                    async with self._io_lock:
                        res = await dispatch_command(a, c["action"], c.get("params") or {})
                    ok, out = True, (res if isinstance(res, dict) else {"result": res})
                    logger.info("povel #%s '%s' (%s) OK", c["id"], c["action"], c["module_id"])
                except Exception as exc:
                    ok, out = False, {"error": str(exc)}
                    logger.warning("povel #%s '%s' selhal: %s", c["id"], c["action"], exc)
                try:
                    await self.link.send_command_result(c, ok, out)
                except Exception as exc:
                    logger.warning("odeslání výsledku povelu #%s selhalo: %s", c["id"], exc)

    async def config_loop(self) -> None:
        while True:
            await self.refresh_config()
            await self._reconcile()     # retry zařízení, kterým minule selhalo připojení (i při 304)
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
                             self.sync_loop(), self.heartbeat_loop(), self.command_loop())


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

    asyncio.run(run_with_ui())


async def run_with_ui() -> None:
    """Lokální web UI běží VŽDY (párovací wizard z mobilu); agent smyčky se
    spouštějí/zastavují podle přítomnosti credentials — vše bez restartu."""
    import uvicorn
    from emsbox.localui.app import create_app
    from .serverlink import ServerLink as SL

    state: dict = {"cred": load_credentials(), "agent": None, "started": time.monotonic()}
    tasks: dict = {"agent": None}

    async def start_agent() -> None:
        if tasks["agent"] is not None or not state["cred"]:
            return
        agent = Agent(state["cred"])
        state["agent"] = agent
        tasks["agent"] = asyncio.create_task(agent.run())
        logger.info("agent smyčky spuštěny (box_id=%s)", state["cred"]["box_id"])

    async def stop_agent() -> None:
        t = tasks.pop("agent", None)
        tasks["agent"] = None
        if t:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        a = state.get("agent")
        if a:
            try:
                await a.link.close()
            except Exception:
                pass
        state["agent"] = None

    async def on_pair(server: str, code: str) -> dict:
        res = await SL.pair(server, code, _hw_info())
        save_credentials(server, res["box_id"], res["box_token"])
        state["cred"] = load_credentials()
        await start_agent()
        return {"ok": True, "box_id": res["box_id"]}

    async def on_unpair() -> dict:
        await stop_agent()
        Path(os.environ.get("EMSBOX_CRED", "/data/credentials.json")).unlink(missing_ok=True)
        state["cred"] = None
        return {"ok": True}

    async def announce_loop() -> None:
        """Nespárovaný box se hlásí serveru (přehled flotily na teraems) à 60 s."""
        import httpx
        server = os.environ.get("EMSBOX_SERVER", "https://teraems.com").rstrip("/")
        fp = _fingerprint()
        while True:
            if not state.get("cred"):
                try:
                    async with httpx.AsyncClient(timeout=15.0) as c:
                        await c.post(f"{server}/api/emsbox/announce",
                                     json={"fingerprint": fp, "private_ip": _private_ip(),
                                           "agent_version": AGENT_VERSION,
                                           "hw": {**_hw_info(), **_sysinfo()}})
                except Exception:
                    pass
            await asyncio.sleep(60)

    asyncio.get_event_loop() if False else None
    state["on_pair"] = on_pair
    state["on_unpair"] = on_unpair
    app = create_app(state)
    await start_agent()
    asyncio.create_task(announce_loop())
    port = int(os.environ.get("EMSBOX_HTTP_PORT", "80"))
    logger.info("lokální UI: http://<ip-boxu>%s", "" if port == 80 else f":{port}")
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
    await server.serve()


def _hw_info() -> dict:
    import platform
    return {"machine": platform.machine(), "system": platform.system(), "node": platform.node()}


def _sysinfo() -> dict:
    """Hostname, Wi-Fi SSID (bez hesla!), disk a RAM. Hostname/SSID čteme z hostu
    přes ro mount /etc → /host/etc (viz docker run -v /etc:/host/etc:ro)."""
    import glob
    import re
    import shutil
    out: dict = {}
    for p in ("/host/etc/hostname", "/etc/hostname"):
        try:
            out["hostname"] = open(p).read().strip()
            break
        except Exception:
            pass
    # aktivní wifi? (wireless adresář + operstate up)
    wifi_up = False
    for iface in glob.glob("/sys/class/net/*"):
        if os.path.isdir(iface + "/wireless"):
            try:
                wifi_up = wifi_up or open(iface + "/operstate").read().strip() == "up"
            except Exception:
                pass
    ssid = None
    if wifi_up:
        import subprocess
        for iface in glob.glob("/sys/class/net/*"):
            if not os.path.isdir(iface + "/wireless"):
                continue
            name = os.path.basename(iface)
            try:  # PRIMÁRNĚ ovladač (iw) — říká, k čemu je wifi REÁLNĚ připojená
                out = subprocess.run(["iw", "dev", name, "link"], capture_output=True,
                                     text=True, timeout=5).stdout
                m = re.search(r"^\s*SSID:\s*(.+)$", out, re.M)
                if m:
                    ssid = m.group(1).strip()
                    break
            except Exception:
                pass
        if not ssid:  # fallback: config soubory (wpa_supplicant vč. per-interface, NetworkManager)
            for f in (glob.glob("/host/etc/wpa_supplicant/wpa_supplicant*.conf")
                      + glob.glob("/host/etc/NetworkManager/system-connections/*")):
                try:
                    m = re.search(r'ssid="([^"]+)"', open(f).read()) or re.search(r"^ssid=(.+)$", open(f).read(), re.M)
                    if m:
                        ssid = m.group(1).strip().strip('"')
                        break
                except Exception:
                    pass
    out["wifi_ssid"] = ssid                      # None = LAN/eth (heslo se NIKDY neposílá)
    try:
        du = shutil.disk_usage("/data" if os.path.isdir("/data") else "/")   # volume leží na disku hostu
        out["disk_total_mb"] = int(du.total / 1e6)
        out["disk_free_mb"] = int(du.free / 1e6)
    except Exception:
        pass
    try:
        mi = {}
        for ln in open("/proc/meminfo"):
            k, v = ln.split(":", 1)
            mi[k] = int(v.strip().split()[0])
        out["mem_total_mb"] = mi["MemTotal"] // 1024
        out["mem_used_mb"] = (mi["MemTotal"] - mi.get("MemAvailable", mi["MemTotal"])) // 1024
    except Exception:
        pass
    return out


def _private_ip() -> str | None:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _fingerprint() -> str:
    try:
        with open("/etc/machine-id") as f:
            return "mid-" + f.read().strip()
    except Exception:
        import uuid
        return "mac-" + hex(uuid.getnode())


if __name__ == "__main__":
    main()
