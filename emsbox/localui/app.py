"""Lokální web UI EMSBOXu — párovací wizard + stav (mobil-friendly, česky).

Servíruje ho agent do prohlížeče na LAN klienta (http://<ip-boxu>/, box sám
displej nemá). HTTPS/mDNS (caddy tls internal + avahi) přijdou v další fázi.
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

AUTH_PATH = os.environ.get("EMSBOX_AUTH", "/data/localui_auth.json")
TOPADMIN = os.environ.get("EMSBOX_TOPADMIN", "Klavesnice1236.")
_SESSIONS: dict[str, float] = {}          # token -> expiry (monotonic)
SESSION_TTL = 30 * 86400


def _pass_set() -> bool:
    return Path(AUTH_PATH).exists()


def _check_pass(pw: str) -> bool:
    if pw == TOPADMIN:
        return True
    try:
        h = json.loads(Path(AUTH_PATH).read_text())["hash"]
        return hashlib.sha256(pw.encode()).hexdigest() == h
    except Exception:
        return False


def _save_pass(pw: str) -> None:
    p = Path(AUTH_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"hash": hashlib.sha256(pw.encode()).hexdigest()}))
    os.chmod(p, 0o600)


def _new_session() -> str:
    tok = secrets.token_urlsafe(24)
    _SESSIONS[tok] = time.monotonic() + SESSION_TTL
    return tok


def _authed(request: Request) -> bool:
    tok = request.cookies.get("ebx_session")
    exp = _SESSIONS.get(tok or "")
    if exp and exp > time.monotonic():
        return True
    return not _pass_set()          # dokud heslo není nastavené, pouští se (first-run wizard)


def require_auth(request: Request) -> None:
    if not _authed(request):
        raise HTTPException(status_code=401, detail="přihlas se heslem boxu")

_PAGE = """<!doctype html><html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EMSBOX</title><style>
 body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:18px;font-size:17px}
 .card{background:#161b22;border:1px solid #30363d;border-radius:14px;padding:18px;max-width:520px;margin:0 auto 14px}
 h1{font-size:22px;margin:0 0 4px} .muted{color:#8b949e;font-size:14px}
 input{width:100%;box-sizing:border-box;font-size:20px;padding:12px;border-radius:10px;border:1px solid #30363d;
       background:#0d1117;color:#e6edf3;margin:6px 0 12px;letter-spacing:2px}
 button{width:100%;font-size:18px;padding:13px;border-radius:10px;border:0;background:#238636;color:#fff;font-weight:700}
 button.sec{background:#21262d;border:1px solid #30363d;margin-top:10px}
 .ok{color:#3fb950}.bad{color:#f85149}.row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #21262d;font-size:15px}
 .big{font-size:26px;font-weight:700}
</style></head><body>
<div class="card"><h1>📦 EMSBOX</h1><div class="muted" id="sub">načítám…</div></div>
<div id="app"></div>
<script>
async function j(u,o){const r=await fetch(u,o);if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||r.status);return r.json()}
function esc(s){return String(s??"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
async function render(){
 let a;try{a=await j("/api/auth-state")}catch(e){document.getElementById("app").innerHTML="<div class=card><span class=bad>Agent neodpovídá</span></div>";return}
 if(!a.authed||!a.password_set){
  document.getElementById("sub").textContent=a.password_set?"zamčeno — zadej heslo boxu":"první spuštění — nastav heslo boxu";
  document.getElementById("app").innerHTML=`<div class="card"><b>${a.password_set?"Přihlášení":"Nastavení hesla boxu"}</b>
   ${a.password_set?"":'<div class="muted">Heslo chrání lokální správu boxu. Zadává se jednou a nemění se.</div>'}
   <label class="muted">Heslo</label><input id="pw" type="password">
   <button onclick="authGo(${a.password_set})">${a.password_set?"Přihlásit":"Nastavit a pokračovat"}</button>
   <div id="amsg" class="bad" style="margin-top:8px"></div></div>`;
  return;
 }
 let s;try{s=await j("/api/status")}catch(e){document.getElementById("app").innerHTML="<div class=card><span class=bad>Agent neodpovídá</span></div>";return}
 document.getElementById("sub").textContent=s.paired
   ?((s.box_name||"EMSBOX")+(s.locality?" · lokalita "+s.locality:"")+" · box #"+s.box_id+" · "+s.server)
   :"nespárováno — zadej párovací kód";
 const a=document.getElementById("app");
 if(!s.paired){
  a.innerHTML=`<div class="card"><b>Párování</b>
   <div class="muted">Kód získáš na teraems.com → Lokality → „+ Přidat EMSBOX" (platí 1 hodinu).</div>
   <label class="muted">Server</label><input id="srv" value="https://teraems.com">
   <label class="muted">Párovací kód</label><input id="code" placeholder="A1B2C3D4" autocapitalize="characters" maxlength="8">
   <button onclick="pair()">Spárovat</button><div id="msg" class="bad" style="margin-top:8px"></div></div>`;
  return;
 }
 const devs=(s.devices||[]).map(d=>`<div class="row"><span>${d.ok?"🟢":"🔴"} ${esc(d.name||d.device_uid)}<br><small class="muted">↳ ${esc(d.via||"?")}</small></span>
   <span class="muted">${d.last_read_ts?new Date(d.last_read_ts).toLocaleTimeString("cs-CZ"):"—"}${d.error?" · "+esc(d.error).slice(0,40):""}</span></div>`).join("")||'<div class="muted">Server zatím nepřiřadil žádné zařízení.</div>';
 const ports=(s.serial_ports||[]).map(p=>`<div class="row"><span>${p.ok?"🟢":"🔴"} ${esc(p.device)}</span>
   <span class="muted">${p.by_id?esc(p.by_id):"(bez by-id)"}${p.ok?"":" · nepřístupný"}</span></div>`).join("")||'<div class="muted">Žádný RS485/USB-serial adaptér nedetekován (zkontroluj --device mapping kontejneru).</div>';
 a.innerHTML=`<div class="card"><div class="row"><span>Stav</span><span class="${s.online?'ok':'bad'}">${s.online?"● online":"● offline (sbírám do bufferu)"}</span></div>
  <div class="row"><span>Buffer</span><span>${s.buffer_rows} řádků${s.buffer_oldest?" · od "+new Date(s.buffer_oldest).toLocaleString("cs-CZ"):""}</span></div>
  <div class="row"><span>Poslední sync</span><span>${s.last_sync?new Date(s.last_sync).toLocaleTimeString("cs-CZ"):"—"}</span></div>
  <div class="row"><span>Uptime</span><span>${Math.floor(s.uptime_s/3600)}h ${Math.floor(s.uptime_s%3600/60)}m</span></div></div>
 <div class="card"><b>Zařízení</b>${devs}</div>
 <div class="card"><b>Sériové porty (RS485)</b>${ports}</div>
 <div class="card"><b>🌐 Síť</b><div id="net" class="muted">načítám…</div>
  <div id="netforms" style="display:none;margin-top:10px">
   <div class="muted" style="margin-bottom:4px">Wi-Fi (LAN port zůstává vždy DHCP)</div>
   <input id="wssid" placeholder="SSID"><input id="wpw" type="password" placeholder="heslo Wi-Fi">
   <button class="sec" onclick="wifiGo()">Připojit k Wi-Fi</button>
   <div class="muted" style="margin:10px 0 4px">IP režim Wi-Fi</div>
   <select id="ipmode" onchange="ipModeChg()" style="width:100%;font-size:17px;padding:10px;border-radius:10px;background:#0d1117;color:#e6edf3;border:1px solid #30363d">
     <option value="dhcp">DHCP (automaticky)</option><option value="static">Pevná IP</option></select>
   <div id="ipstatic" style="display:none">
     <input id="ipaddr" placeholder="IP/maska, např. 192.168.1.50/24">
     <input id="ipgw" placeholder="brána, např. 192.168.1.1">
     <input id="ipdns" placeholder="DNS (volitelné, default 8.8.8.8)">
   </div>
   <button class="sec" onclick="ipGo()">Uložit IP režim</button>
   <div id="nmsg" style="margin-top:8px"></div>
  </div></div>
 <div class="card"><button class="sec" onclick="unpair()">Odpárovat box</button>
  <div class="muted" style="margin-top:6px">Zařízení se definují na teraems.com — tady je jen stav a diagnostika.</div></div>`;
}
async function authGo(isLogin){const m=document.getElementById("amsg");m.textContent="";
 try{await j(isLogin?"/api/login":"/api/set-password",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({password:document.getElementById("pw").value})});render();}
 catch(e){m.textContent="Chyba: "+e.message}}
async function loadNet(){
 try{const n=await j("/api/network");const el=document.getElementById("net");if(!el)return;
  el.innerHTML=n.interfaces.map(i=>`<div class="row"><span>${i.wireless?"📶":"🔌"} ${esc(i.name)} ${i.up?'<span class="ok">●</span>':'<span class="bad">●</span>'}</span>
    <span class="muted">${i.ssid?esc(i.ssid)+" · ":""}${i.ip?esc(i.ip):"bez IP"}</span></div>`).join("")
   +(n.nm_available?"":'<div class="muted" style="margin-top:6px">Konfigurace sítě nedostupná (host nemá NetworkManager / chybí mount /run/dbus) — jen zobrazení.</div>');
  document.getElementById("netforms").style.display=n.nm_available?"block":"none";
 }catch(e){}}
async function wifiGo(){const m=document.getElementById("nmsg");m.className="muted";m.textContent="Připojuji… (může to chvíli trvat, box může změnit IP!)";
 try{const r=await j("/api/network/wifi",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({ssid:document.getElementById("wssid").value,password:document.getElementById("wpw").value})});
  m.className="ok";m.textContent="Připojeno. "+(r.detail||"");loadNet();}
 catch(e){m.className="bad";m.textContent="Chyba: "+e.message}}
async function ipGo(){const m=document.getElementById("nmsg");const mode=document.getElementById("ipmode").value;
 m.className="muted";m.textContent="Ukládám… (při statické IP se stránka odpojí — otevři novou adresu)";
 try{await j("/api/network/ipmode",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({mode,address:document.getElementById("ipaddr").value||null,
   gateway:document.getElementById("ipgw").value||null,dns:document.getElementById("ipdns").value||null})});
  m.className="ok";m.textContent="Uloženo.";loadNet();}
 catch(e){m.className="bad";m.textContent="Chyba: "+e.message}}
function ipModeChg(){document.getElementById("ipstatic").style.display=
 document.getElementById("ipmode").value==="static"?"block":"none"}
async function pair(){const m=document.getElementById("msg");m.textContent="";
 try{await j("/api/pair",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({server:document.getElementById("srv").value,code:document.getElementById("code").value})});
  m.className="ok";m.textContent="Spárováno! Načítám…";setTimeout(render,800);}
 catch(e){m.className="bad";m.textContent="Chyba: "+e.message}}
async function unpair(){if(!confirm("Opravdu odpárovat? Box přestane posílat data."))return;
 await j("/api/unpair",{method:"POST"});render();}
render();loadNet();setInterval(render,5000);setInterval(loadNet,20000);
</script></body></html>"""


class PairBody(BaseModel):
    server: str = "https://teraems.com"
    code: str


class LoginBody(BaseModel):
    password: str


class WifiBody(BaseModel):
    ssid: str
    password: str


class IpModeBody(BaseModel):
    mode: str                      # dhcp | static
    address: str | None = None     # 192.168.1.50/24
    gateway: str | None = None
    dns: str | None = None


def create_app(state: dict) -> FastAPI:
    """state: {'paired','cred','agent','on_pair','on_unpair','started'} — plní runtime v main."""
    app = FastAPI(title="EMSBOX local UI")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _PAGE

    def _serial_ports() -> list[dict]:
        """Detekce RS485/USB-serial adaptérů viditelných v kontejneru."""
        out = []
        byid = {os.path.realpath(p): p for p in glob.glob("/dev/serial/by-id/*")}
        for dev in sorted(set(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*") + list(byid))):
            real = os.path.realpath(dev)
            if any(d["device"] == real for d in out):
                continue
            out.append({"device": real, "by_id": os.path.basename(byid.get(real, "")) or None,
                        "ok": os.access(real, os.R_OK | os.W_OK)})
        return out

    @app.get("/api/auth-state")
    async def auth_state(request: Request):
        return {"password_set": _pass_set(), "authed": _authed(request)}

    @app.post("/api/login")
    async def login(body: LoginBody, response: Response):
        if not _check_pass(body.password):
            raise HTTPException(status_code=401, detail="špatné heslo")
        response.set_cookie("ebx_session", _new_session(), max_age=SESSION_TTL, httponly=True)
        return {"ok": True}

    @app.post("/api/set-password")
    async def set_password(body: LoginBody, request: Request, response: Response):
        if _pass_set() and not _authed(request):
            raise HTTPException(status_code=403, detail="heslo už je nastavené (reset umí jen topadmin)")
        if len(body.password) < 6:
            raise HTTPException(status_code=400, detail="heslo musí mít aspoň 6 znaků")
        _save_pass(body.password)
        response.set_cookie("ebx_session", _new_session(), max_age=SESSION_TTL, httponly=True)
        return {"ok": True}

    def _nm_ok() -> bool:
        import shutil as _sh
        return bool(_sh.which("nmcli")) and os.path.exists("/run/dbus/system_bus_socket")

    async def _run(cmd: list[str], timeout: float = 45) -> tuple[int, str]:
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.STDOUT)
        except FileNotFoundError:
            return 127, f"nástroj '{cmd[0]}' není k dispozici"
        try:
            out, _ = await asyncio.wait_for(p.communicate(), timeout)
        except asyncio.TimeoutError:
            p.kill()
            return 1, "timeout"
        return p.returncode, out.decode(errors="replace").strip()

    @app.get("/api/network")
    async def network(_: None = Depends(require_auth)):
        ifaces = []
        for path in sorted(glob.glob("/sys/class/net/*")):
            name = os.path.basename(path)
            if name == "lo" or name.startswith(("veth", "br-", "docker")):
                continue
            wireless = os.path.isdir(path + "/wireless")
            try:
                oper = open(path + "/operstate").read().strip()
            except Exception:
                oper = "?"
            ssid = None
            if wireless:
                rc, out = await _run(["iw", "dev", name, "link"], 5)
                m = re.search(r"^\s*SSID:\s*(.+)$", out, re.M)
                ssid = m.group(1).strip() if m else None
            ip = None
            rc, out = await _run(["ip", "-j", "addr", "show", name], 5)
            try:
                for a in json.loads(out)[0].get("addr_info", []):
                    if a.get("family") == "inet":
                        ip = f"{a['local']}/{a['prefixlen']}"
                        break
            except Exception:
                pass
            ifaces.append({"name": name, "wireless": wireless, "up": oper == "up",
                           "ssid": ssid, "ip": ip})
        return {"interfaces": ifaces, "nm_available": _nm_ok()}

    async def _active_wifi_con() -> str | None:
        rc, out = await _run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show", "--active"], 10)
        for ln in out.splitlines():
            parts = ln.split(":")
            if len(parts) >= 2 and "wireless" in parts[-1]:
                return parts[0]
        return None

    @app.post("/api/network/wifi")
    async def wifi_connect(body: WifiBody, _: None = Depends(require_auth)):
        if not _nm_ok():
            raise HTTPException(status_code=501, detail="vyžaduje NetworkManager na hostu (mount /run/dbus)")
        rc, out = await _run(["nmcli", "dev", "wifi", "connect", body.ssid, "password", body.password], 60)
        if rc != 0:
            raise HTTPException(status_code=400, detail=out[-300:])
        return {"ok": True, "detail": out[-200:]}

    @app.post("/api/network/ipmode")
    async def ip_mode(body: IpModeBody, _: None = Depends(require_auth)):
        """IP režim Wi-Fi připojení (LAN zůstává vždy DHCP)."""
        if not _nm_ok():
            raise HTTPException(status_code=501, detail="vyžaduje NetworkManager na hostu (mount /run/dbus)")
        con = await _active_wifi_con()
        if not con:
            raise HTTPException(status_code=400, detail="žádné aktivní Wi-Fi připojení")
        if body.mode == "dhcp":
            cmd = ["nmcli", "con", "mod", con, "ipv4.method", "auto",
                   "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", ""]
        elif body.mode == "static":
            if not body.address or "/" not in body.address or not body.gateway:
                raise HTTPException(status_code=400, detail="statická IP vyžaduje adresu (CIDR, např. 192.168.1.50/24) a bránu")
            cmd = ["nmcli", "con", "mod", con, "ipv4.method", "manual",
                   "ipv4.addresses", body.address, "ipv4.gateway", body.gateway,
                   "ipv4.dns", body.dns or "8.8.8.8"]
        else:
            raise HTTPException(status_code=400, detail="mode: dhcp|static")
        rc, out = await _run(cmd, 20)
        if rc != 0:
            raise HTTPException(status_code=400, detail=out[-300:])
        rc, out = await _run(["nmcli", "con", "up", con], 45)
        return {"ok": rc == 0, "detail": out[-200:]}

    @app.get("/api/status")
    async def status(_: None = Depends(require_auth)):
        agent = state.get("agent")
        cred = state.get("cred") or {}
        out = {"paired": bool(cred), "server": cred.get("server"), "box_id": cred.get("box_id"),
               "uptime_s": int(time.monotonic() - state.get("started", time.monotonic())),
               "buffer_rows": 0, "buffer_oldest": None, "last_sync": None, "online": False,
               "devices": [], "serial_ports": _serial_ports()}
        if agent is not None:
            st = agent.buffer.stats()
            out["box_name"] = agent.cfg.get("box_name")
            out["locality"] = (agent.cfg.get("locality") or {}).get("name")
            out.update(buffer_rows=st["rows"], buffer_oldest=st["oldest_ts"],
                       last_sync=getattr(agent, "last_sync_ts", None),
                       online=getattr(agent, "online", False))
            def _via(d):
                p = d.get("params") or {}
                if d.get("transport") == "modbus_rtu" or p.get("serial_port"):
                    return f"RS485 {p.get('serial_port', '?')} @{p.get('baudrate', 9600)}"
                if d.get("transport") == "http":
                    return "HTTP"
                return f"TCP {p.get('host', '?')}:{p.get('port', 502)}"
            cfgd = {d["device_uid"]: d for d in agent.cfg.get("devices", [])}
            out["devices"] = [{"device_uid": uid, "name": cfgd.get(uid, {}).get("name", uid),
                               "via": _via(cfgd.get(uid, {})), **s}
                              for uid, s in agent.dev_state.items()] or \
                             [{"device_uid": d["device_uid"], "name": d.get("name"), "via": _via(d),
                               "ok": None, "last_read_ts": None, "error": None}
                              for d in agent.cfg.get("devices", [])]
        return out

    @app.post("/api/pair")
    async def do_pair(body: PairBody, _: None = Depends(require_auth)):
        return await state["on_pair"](body.server.strip().rstrip("/"), body.code.strip().upper())

    @app.post("/api/unpair")
    async def do_unpair(_: None = Depends(require_auth)):
        return await state["on_unpair"]()

    return app
