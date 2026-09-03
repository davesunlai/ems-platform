"""Lokální web UI EMSBOXu — párovací wizard + stav (mobil-friendly, česky).

Servíruje ho agent do prohlížeče na LAN klienta (http://<ip-boxu>/, box sám
displej nemá). HTTPS/mDNS (caddy tls internal + avahi) přijdou v další fázi.
"""
from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

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
 let s;try{s=await j("/api/status")}catch(e){document.getElementById("app").innerHTML="<div class=card><span class=bad>Agent neodpovídá</span></div>";return}
 document.getElementById("sub").textContent=s.paired?("spárováno se "+s.server+" · box #"+s.box_id):"nespárováno — zadej párovací kód";
 const a=document.getElementById("app");
 if(!s.paired){
  a.innerHTML=`<div class="card"><b>Párování</b>
   <div class="muted">Kód získáš na teraems.com → Lokality → „+ Přidat EMSBOX" (platí 1 hodinu).</div>
   <label class="muted">Server</label><input id="srv" value="https://teraems.com">
   <label class="muted">Párovací kód</label><input id="code" placeholder="A1B2C3D4" autocapitalize="characters" maxlength="8">
   <button onclick="pair()">Spárovat</button><div id="msg" class="bad" style="margin-top:8px"></div></div>`;
  return;
 }
 const devs=(s.devices||[]).map(d=>`<div class="row"><span>${d.ok?"🟢":"🔴"} ${esc(d.name||d.device_uid)}</span>
   <span class="muted">${d.last_read_ts?new Date(d.last_read_ts).toLocaleTimeString("cs-CZ"):"—"}${d.error?" · "+esc(d.error).slice(0,40):""}</span></div>`).join("")||'<div class="muted">Server zatím nepřiřadil žádné zařízení.</div>';
 a.innerHTML=`<div class="card"><div class="row"><span>Stav</span><span class="${s.online?'ok':'bad'}">${s.online?"● online":"● offline (sbírám do bufferu)"}</span></div>
  <div class="row"><span>Buffer</span><span>${s.buffer_rows} řádků${s.buffer_oldest?" · od "+new Date(s.buffer_oldest).toLocaleString("cs-CZ"):""}</span></div>
  <div class="row"><span>Poslední sync</span><span>${s.last_sync?new Date(s.last_sync).toLocaleTimeString("cs-CZ"):"—"}</span></div>
  <div class="row"><span>Uptime</span><span>${Math.floor(s.uptime_s/3600)}h ${Math.floor(s.uptime_s%3600/60)}m</span></div></div>
 <div class="card"><b>Zařízení</b>${devs}</div>
 <div class="card"><button class="sec" onclick="unpair()">Odpárovat box</button>
  <div class="muted" style="margin-top:6px">Zařízení se definují na teraems.com — tady je jen stav a diagnostika.</div></div>`;
}
async function pair(){const m=document.getElementById("msg");m.textContent="";
 try{await j("/api/pair",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({server:document.getElementById("srv").value,code:document.getElementById("code").value})});
  m.className="ok";m.textContent="Spárováno! Načítám…";setTimeout(render,800);}
 catch(e){m.className="bad";m.textContent="Chyba: "+e.message}}
async function unpair(){if(!confirm("Opravdu odpárovat? Box přestane posílat data."))return;
 await j("/api/unpair",{method:"POST"});render();}
render();setInterval(render,5000);
</script></body></html>"""


class PairBody(BaseModel):
    server: str = "https://teraems.com"
    code: str


def create_app(state: dict) -> FastAPI:
    """state: {'paired','cred','agent','on_pair','on_unpair','started'} — plní runtime v main."""
    app = FastAPI(title="EMSBOX local UI")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _PAGE

    @app.get("/api/status")
    async def status():
        agent = state.get("agent")
        cred = state.get("cred") or {}
        out = {"paired": bool(cred), "server": cred.get("server"), "box_id": cred.get("box_id"),
               "uptime_s": int(time.monotonic() - state.get("started", time.monotonic())),
               "buffer_rows": 0, "buffer_oldest": None, "last_sync": None, "online": False, "devices": []}
        if agent is not None:
            st = agent.buffer.stats()
            out.update(buffer_rows=st["rows"], buffer_oldest=st["oldest_ts"],
                       last_sync=getattr(agent, "last_sync_ts", None),
                       online=getattr(agent, "online", False))
            names = {d["device_uid"]: d.get("name") for d in agent.cfg.get("devices", [])}
            out["devices"] = [{"device_uid": uid, "name": names.get(uid, uid), **s}
                              for uid, s in agent.dev_state.items()] or \
                             [{"device_uid": d["device_uid"], "name": d.get("name"), "ok": None,
                               "last_read_ts": None, "error": None} for d in agent.cfg.get("devices", [])]
        return out

    @app.post("/api/pair")
    async def do_pair(body: PairBody):
        return await state["on_pair"](body.server.strip().rstrip("/"), body.code.strip().upper())

    @app.post("/api/unpair")
    async def do_unpair():
        return await state["on_unpair"]()

    return app
