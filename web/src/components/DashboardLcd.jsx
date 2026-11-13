// 📟 Rozhraní „Panel měniče (LCD)“ — alternativní dashboard ve stylu displeje střídače (zadání 13. 11. 2026, alternativnirozhrani01.pdf).
// Stejná data jako schéma TERA, jiná prezentace. Navigace jako na displeji:
//   HOME (Current Status: schéma toku) ─MENU→ Hlavní menu: PLANT INFORMATION · ALARM INFORMATION · SYSTEM SETTING · PROFESSIONAL SETTING
//   PLANT INFORMATION: záložky PV · BATT · GRID · LOAD · MORE, každá s „Historie = ENTER“ → MĚSÍC (dny) · ROK (měsíce) · CELKEM (roky)
//   SYSTEM SETTING: podmenu STORAGE MODE · BATTERY SETTING · BASIC SETTING · SMART PORT · GRID PORT · MORE FUNCTION (přehled, odkazy do TERA)
//   ← Zpět v liště vrací o úroveň (zásobník obrazovek). Virtuální plocha 960×540, škáluje se na šířku (mobil, otočení).
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { BatteryTestButton } from "./BatteryTest";

const W = 960, H = 540;
const PLANT_TABS = [["pv", "PV"], ["batt", "BATT"], ["grid", "GRID"], ["load", "LOAD"], ["more", "MORE"]];
const HIST_TABS = [["day", "MĚSÍC"], ["month", "ROK"], ["year", "CELKEM"]];
const STATE_TXT = { 15: "Normální", 3: "Výroba", 4121: "Alarm IGFOL-F (1019)", 0: "Čekání", 1: "Start", 2: "Start", 4: "Alarm", 5: "Chyba" };
const HIST_DEF = {
  pv: { title: "Historie výroby", series: [["pv", "Výroba", "#2f6fd0"]] },
  batt: { title: "Historie nabíjení a vybíjení", series: [["bat_chg", "Nabíjení", "#2f6fd0"], ["bat_dis", "Vybíjení", "#e3c320"]] },
  grid: { title: "Historie nákupu a prodeje", series: [["imp", "Nákup", "#2f6fd0"], ["exp", "Prodej", "#e3c320"]] },
  load: { title: "Historie spotřeby", series: [["load", "Spotřeba", "#2f6fd0"]] },
  more: { title: "Historie energií", series: [["pv", "Výroba", "#2f6fd0"], ["load", "Spotřeba", "#e3c320"], ["imp", "Nákup", "#8fa3bd"]] },
};

const css = `
.lcd{position:relative;width:${W}px;height:${H}px;background:#eef3f9;color:#1b2a3a;font-family:Inter,Segoe UI,Arial,sans-serif;border-radius:8px;overflow:hidden;box-shadow:0 2px 14px rgba(0,0,0,.35);transform-origin:top left;user-select:none}
.lcd *{box-sizing:border-box}
.lcd .bar{height:44px;background:linear-gradient(#2c6fd1,#1d55b0);color:#fff;display:flex;align-items:center;padding:0 14px;gap:4px;font-size:15px;font-weight:600;letter-spacing:.3px}
.lcd .bar .back{background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.45);color:#fff;border-radius:6px;padding:4px 10px;font-size:13px;cursor:pointer;margin-right:10px}
.lcd .bar .tab{padding:10px 12px 9px;border-bottom:3px solid transparent;opacity:.72;cursor:pointer;font-size:14px}
.lcd .bar .tab.on{opacity:1;border-bottom-color:#fff;background:rgba(255,255,255,.12)}
.lcd .bar .clock{margin-left:auto;font-weight:500;font-size:14px;opacity:.95;font-variant-numeric:tabular-nums}
.lcd .body{position:absolute;inset:44px 0 0 0;padding:14px 22px}
.lcd table{border-collapse:collapse;font-size:15px}
.lcd td,.lcd th{padding:5px 14px;text-align:left;white-space:nowrap}
.lcd th{color:#2457a8;font-weight:600}
.lcd td.l{color:#44556a}
.lcd td.v{font-variant-numeric:tabular-nums;font-weight:600}
.lcd .hdr{font-size:15px;color:#1b2a3a;margin:4px 0 10px 0;font-weight:600}
.lcd .hdr span{color:#44556a;font-weight:400}
.lcd .foot{position:absolute;left:0;right:0;bottom:12px;text-align:center;display:flex;justify-content:center;gap:12px}
.lcd .foot button,.lcd .foot a,.lcd .ebtn{background:#cfe2f8;color:#1b2a3a;border:1px solid #9fc0ea;border-radius:6px;padding:6px 16px;font-size:13px;cursor:pointer;text-decoration:none;display:inline-block}
.lcd .flow{stroke-dasharray:8 6;animation:lcdflow 1s linear infinite}
@keyframes lcdflow{to{stroke-dashoffset:-14}}
.lcd .menu{display:grid;grid-template-columns:1fr 1fr;gap:16px 36px;padding:26px 70px}
.lcd .menu div{background:#fff;border:1px solid #b8cde8;border-radius:10px;padding:22px 20px;font-size:17px;font-weight:600;color:#1d4f9c;cursor:pointer;display:flex;align-items:center;gap:14px}
.lcd .menu div:hover{background:#e3eefb}
.lcd .menu div small{display:block;font-size:12px;font-weight:400;color:#44556a;margin-top:2px}
.lcd .menu .ico{font-size:26px;width:36px;text-align:center}
.lcd .kv{display:grid;grid-template-columns:auto 1fr;gap:6px 24px;font-size:15px}
.lcd .kv span:nth-child(odd){color:#44556a}
.lcd .kv span:nth-child(even){font-weight:600}
.lcd .per{display:flex;align-items:center;gap:10px;font-size:15px;margin:2px 0 6px}
.lcd .per button{background:#fff;border:1px solid #9fc0ea;border-radius:6px;padding:2px 10px;font-size:14px;cursor:pointer}
.lcd .per button:disabled{opacity:.4;cursor:default}
`;

function useScale(ref) {
  const [s, setS] = useState(1);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const upd = () => { const w = el.getBoundingClientRect().width || el.clientWidth || W; setS(Math.min(1.2, Math.max(0.3, (w - 2) / W))); };
    upd();
    const ro = new ResizeObserver(upd); ro.observe(el);
    window.addEventListener("orientationchange", upd);
    return () => { ro.disconnect(); window.removeEventListener("orientationchange", upd); };
  }, [ref]);
  return s;
}

const num = (v, d = 1) => (v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(d).replace(".", ","));
const kW = (w, d = 2) => (w == null ? "—" : `${num(w / 1000, d)} kW`);
const kwh = (v, d = 1) => (v == null ? "—" : `${num(v, d)} kWh`);

// ---------- kontejner lokality: data + navigace ----------
export function LcdLocality({ name, devs }) {
  const ids = devs.map((d) => d.device_id);
  const locId = devs[0].locality_id;
  const solis = devs.find((d) => d.adapter === "solis")?.device_id || ids[0];
  const [nav, setNav] = useState(() => { try { return JSON.parse(sessionStorage.getItem(`lcd.nav.${locId}`) || "null") || [{ s: "home" }]; } catch { return [{ s: "home" }]; } });
  const [d, setD] = useState(null);           // aggregate-now
  const [m, setM] = useState({});             // latest metriky Solisu
  const [blocks, setBlocks] = useState([]);
  const [en, setEn] = useState(null);
  const [cfg, setCfg] = useState({});
  const [now, setNow] = useState(new Date());
  const wrap = useRef(null);
  const scale = useScale(wrap);
  const { has } = useAuth();
  useEffect(() => { sessionStorage.setItem(`lcd.nav.${locId}`, JSON.stringify(nav)); }, [nav, locId]);
  useEffect(() => {
    let alive = true;
    const load = () => {
      api.aggregateNow(ids, locId).then((r) => alive && setD(r)).catch(() => {});
      api.latest(solis).then((l) => alive && setM(l.metrics || {})).catch(() => {});
    };
    load(); const t = setInterval(load, 10000);
    api.btBlocks(solis).then((b) => alive && setBlocks(b || [])).catch(() => {});
    api.getPlanner(locId).then((r) => alive && setCfg(r?.config || {})).catch(() => {});
    const en_ = () => api.btEnergy(locId).then((r) => alive && setEn(r)).catch(() => {});
    en_(); const t2 = setInterval(en_, 30000);
    const t3 = setInterval(() => setNow(new Date()), 1000);
    return () => { alive = false; clearInterval(t); clearInterval(t2); clearInterval(t3); };
    /* eslint-disable-next-line */ }, [locId, solis]);
  const v = (k) => (m[k] ? Number(m[k].value) : null);
  const st = v("inverter_state");
  const stTxt = st == null ? "—" : (STATE_TXT[st] || `kód ${st}`);
  const stBad = st != null && ![15, 3, 0, 1, 2].includes(st);
  const dt = now.toLocaleString("cs-CZ", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const cur = nav[nav.length - 1];
  const push = (s) => setNav((n) => [...n, s]);
  const back = () => setNav((n) => (n.length > 1 ? n.slice(0, -1) : n));
  const replace = (s) => setNav((n) => [...n.slice(0, -1), { ...n[n.length - 1], ...s }]);
  const ctx = { d, v, m, en, cfg, blocks, devs, solis, locId, name, has, push, replace, back };

  let title = `Stav: ${stTxt}`; let tabs = null; let body;
  if (!d) body = <p style={{ padding: 20 }}>Načítám…</p>;
  else switch (cur.s) {
    case "menu": title = "HLAVNÍ MENU"; body = <MainMenu {...ctx} />; break;
    case "plant": {
      const tab = cur.tab || "pv"; title = "INFORMACE O ELEKTRÁRNĚ";
      tabs = PLANT_TABS.map(([k, l]) => <span key={k} className={`tab${tab === k ? " on" : ""}`} onClick={() => replace({ tab: k })}>{l}</span>);
      body = { pv: <PvTab {...ctx} />, batt: <BattTab {...ctx} />, grid: <GridTab {...ctx} />, load: <LoadTab {...ctx} />, more: <MoreTab {...ctx} /> }[tab];
      break;
    }
    case "hist": {
      const per = cur.per || "day"; title = HIST_DEF[cur.kind]?.title || "Historie";
      tabs = HIST_TABS.map(([k, l]) => <span key={k} className={`tab${per === k ? " on" : ""}`} onClick={() => replace({ per: k, at: null })}>{l}</span>);
      body = <HistoryScreen locId={locId} kind={cur.kind} period={per} at={cur.at} onAt={(at) => replace({ at })} />;
      break;
    }
    case "alarms": title = "VÝSTRAHY"; body = <AlarmsScreen locId={locId} />; break;
    case "sys": title = "NASTAVENÍ SYSTÉMU"; body = <SysMenu {...ctx} />; break;
    case "sys.storage": title = "REŽIM ÚLOŽIŠTĚ"; body = <StorageMode {...ctx} />; break;
    case "sys.battery": title = "NASTAVENÍ BATERIE"; body = <BatterySetting {...ctx} />; break;
    case "sys.basic": title = "ZÁKLADNÍ NASTAVENÍ"; body = <BasicSetting {...ctx} now={now} />; break;
    case "sys.smart": title = "CHYTRÉ VÝSTUPY"; body = <SmartPort {...ctx} />; break;
    case "sys.grid": title = "PŘIPOJENÍ K SÍTI"; body = <GridPort {...ctx} />; break;
    case "sys.more": title = "DALŠÍ FUNKCE"; body = <MoreFunction {...ctx} />; break;
    case "pro": title = "SERVISNÍ NASTAVENÍ"; body = <ProSetting {...ctx} />; break;
    default: body = <StatusTab {...ctx} />;
  }

  return (
    <section style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "0 0 6px" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>📟 {name}</h2>
        <span className="muted" style={{ fontSize: 12 }}>· panel měniče · {solis}</span>
      </div>
      <div ref={wrap} style={{ width: "100%", height: Math.round(H * scale), overflow: "hidden" }}>
        <style>{css}</style>
        <div className="lcd" style={{ transform: `scale(${scale})` }}>
          <div className="bar">
            {nav.length > 1 && <button type="button" className="back" onClick={back}>◀ Zpět</button>}
            <span style={{ marginRight: 12, color: stBad && cur.s === "home" ? "#ffd3d3" : "#fff" }}>{title}</span>
            {tabs}
            <span className="clock">{dt}</span>
          </div>
          <div className="body">{body}</div>
        </div>
      </div>
    </section>
  );
}

// ---------- HOME: schéma toku ----------
function StatusTab({ d, v, en, push }) {
  const pv = d.pv_w || 0, bat = d.battery_w || 0, grid = d.grid_w || 0, load = d.load_w || 0, bk = d.backup_w || 0;
  const on = (w) => Math.abs(w) > 50;
  const soc1 = d.battery_soc_1, soc2 = d.battery_soc_2;
  const kwhOf = (i) => en?.blocks?.find((b) => b.idx === i)?.kwh_usable;
  const Bat = ({ x, soc, volt, kwhU, n }) => (
    <g>
      <rect x={x + 14} y={300} width={16} height={6} rx={2} fill="#4a5a6e" />
      <rect x={x} y={306} width={44} height={96} rx={6} fill="#fff" stroke="#4a5a6e" strokeWidth="2" />
      {soc != null && <rect x={x + 4} y={306 + 92 - 88 * Math.max(0, Math.min(100, soc)) / 100} width={36} height={88 * Math.max(0, Math.min(100, soc)) / 100} rx={3} fill={soc > 30 ? "#3bb54a" : soc > 15 ? "#e0a020" : "#d9534f"} />}
      <text x={x + 22} y={420} textAnchor="middle" fontSize="14" fontWeight="600">{soc != null ? `${Math.round(soc)} %` : "—"}</text>
      <text x={x + 22} y={436} textAnchor="middle" fontSize="12" fill="#44556a">{volt != null ? `${num(volt, 1)} V` : ""}</text>
      {kwhU != null && <text x={x + 22} y={451} textAnchor="middle" fontSize="11" fill="#2457a8">{num(kwhU, 1)} kWh</text>}
      <text x={x + 22} y={292} textAnchor="middle" fontSize="11" fill="#44556a">B{n}</text>
    </g>);
  const Arrow = ({ d: path, w, rev, label, lx, ly, color = "#e08a1e" }) => (
    <g>
      <path d={path} fill="none" stroke="#9fb3c8" strokeWidth="6" strokeLinecap="round" />
      {on(w) && <path d={path} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" className="flow" style={rev ? { animationDirection: "reverse" } : undefined} />}
      <text x={lx} y={ly} textAnchor="middle" fontSize="15" fontWeight="600" fill="#1b2a3a">{label}</text>
    </g>);
  return (
    <>
      <svg viewBox="0 0 916 440" width="916" height="440" style={{ display: "block" }}>
        <g transform="translate(40,70)">
          <polygon points="0,60 90,60 120,0 30,0" fill="#2f6fd0" stroke="#163f80" strokeWidth="2" />
          {[30, 60, 90].map((x) => <line key={x} x1={x} y1={0} x2={x - 30} y2={60} stroke="#163f80" strokeWidth="1" />)}
          <line x1={15} y1={30} x2={105} y2={30} stroke="#163f80" strokeWidth="1" />
          <text x={60} y={85} textAnchor="middle" fontSize="12" fill="#44556a">FVE</text>
        </g>
        <Arrow d="M170,100 L330,100" w={pv} label={kW(pv)} lx={250} ly={88} />
        <rect x={330} y={60} width={130} height={200} rx={6} fill="#fff" stroke="#4a5a6e" strokeWidth="2" />
        <rect x={365} y={110} width={60} height={34} rx={4} fill="#dfe8f4" stroke="#9fb3c8" />
        <text x={395} y={240} textAnchor="middle" fontSize="12" fill="#44556a">měnič</text>
        <Bat x={60} soc={soc1} volt={v("battery_voltage_1")} kwhU={kwhOf(1)} n={1} />
        <Bat x={130} soc={soc2} volt={v("battery_voltage_2")} kwhU={kwhOf(2)} n={2} />
        <text x={200} y={325} fontSize="12" fill={v("battery_cell_vmin_1") != null ? "#2d8a3e" : "#a33"}>BMS 1 {v("battery_cell_vmin_1") != null ? "OK" : "—"}</text>
        <text x={200} y={345} fontSize="12" fill={v("battery_cell_vmin_2") != null ? "#2d8a3e" : "#a33"}>BMS 2 {v("battery_cell_vmin_2") != null ? "OK" : "—"}</text>
        <Arrow d="M330,220 L250,220 L250,300" w={bat} rev={bat < 0} label={`${bat > 50 ? "▲ nabíjení" : bat < -50 ? "▼ vybíjení" : ""} ${kW(Math.abs(bat))}`} lx={250} ly={206} color={bat >= 0 ? "#3bb54a" : "#e08a1e"} />
        <Arrow d="M460,100 L600,100" w={load} label={kW(load)} lx={530} ly={88} />
        <g transform="translate(600,60)">
          <polygon points="0,40 45,5 90,40" fill="#d9534f" />
          <rect x={10} y={40} width={70} height={45} fill="#fff" stroke="#4a5a6e" strokeWidth="2" />
          <rect x={38} y={58} width={16} height={27} fill="#4a5a6e" />
          <text x={45} y={105} textAnchor="middle" fontSize="12" fill="#44556a">dům</text>
        </g>
        <Arrow d="M460,180 L600,180" w={bk} label={bk > 50 ? kW(bk) : "0,00 kW"} lx={530} ly={168} color="#39a0c5" />
        <g transform="translate(610,150)">
          <circle cx={30} cy={28} r={22} fill="#fff" stroke="#4a5a6e" strokeWidth="2" />
          <path d="M22,40 L38,40 L38,50 L22,50 Z" fill="#4a5a6e" />
          <path d="M30,10 L30,24 M20,16 L24,24 M40,16 L36,24" stroke="#e0a020" strokeWidth="2" />
          <text x={30} y={70} textAnchor="middle" fontSize="12" fill="#44556a">záloha</text>
        </g>
        <Arrow d="M460,250 L760,250" w={grid} rev={grid < 0} label={`${grid > 50 ? "◀ odběr" : grid < -50 ? "dodávka ▶" : ""} ${kW(Math.abs(grid))}`} lx={610} ly={272} color="#e0a020" />
        <g transform="translate(770,200)">
          <path d="M30,0 L10,100 M30,0 L50,100 M0,100 L60,100 M14,40 L46,40 M10,65 L50,65 M18,20 L42,20" stroke="#4a5a6e" strokeWidth="2.5" fill="none" />
          <text x={30} y={120} textAnchor="middle" fontSize="12" fill="#44556a">síť</text>
        </g>
        <g fontSize="14" fill="#1b2a3a">
          <text x={330} y={310}>Výroba dnes: <tspan fontWeight="600">{kwh(d.today_kwh)}</tspan></text>
          <text x={330} y={332}>Nákup dnes: <tspan fontWeight="600">{kwh(d.import_kwh)}</tspan> · Prodej dnes: <tspan fontWeight="600">{kwh(d.export_kwh)}</tspan></text>
          <text x={330} y={354}>Spotřeba dnes: <tspan fontWeight="600">{kwh(d.cons_today_kwh)}</tspan></text>
          {en && <text x={330} y={376}>Využitelné v baterii: <tspan fontWeight="600" fill="#2457a8">{num(en.total_usable_kwh, 1)} kWh</tspan> <tspan fill="#44556a">(do {en.floor_pct ?? 10} %, test #{en.test_id})</tspan></text>}
          {d.xcheck?.battery_power_inv != null && <text x={330} y={402} fontSize="12" fill="#44556a">měnič hlásí baterii {kW(d.xcheck.battery_power_inv)} · dům {d.xcheck.house_load_inv != null ? kW(d.xcheck.house_load_inv) : "—"}</text>}
        </g>
      </svg>
      <div className="foot"><button type="button" onClick={() => push({ s: "menu" })}>MENU = ‹ ENTER ›</button></div>
    </>
  );
}

// ---------- hlavní menu ----------
function MainMenu({ push, has }) {
  return (
    <div className="menu">
      <div onClick={() => push({ s: "plant", tab: "pv" })}><span className="ico">🏭</span><span>INFORMACE O ELEKTRÁRNĚ<small>PV · BATT · GRID · LOAD · MORE · historie</small></span></div>
      <div onClick={() => push({ s: "alarms" })}><span className="ico">🔔</span><span>VÝSTRAHY<small>události, odstávky, poruchy</small></span></div>
      <div onClick={() => push({ s: "sys" })}><span className="ico">⚙️</span><span>NASTAVENÍ SYSTÉMU<small>režim úložiště, baterie, síť, výstupy</small></span></div>
      <div onClick={() => push({ s: "pro" })} style={{ opacity: has("admin") ? 1 : 0.6 }}><span className="ico">🔧</span><span>SERVISNÍ NASTAVENÍ<small>{has("admin") ? "moduly, diagnostika, registry" : "jen pro servis / správce"}</small></span></div>
    </div>
  );
}

function SysMenu({ push }) {
  return (
    <div className="menu" style={{ gridTemplateColumns: "1fr 1fr", padding: "16px 60px", gap: "12px 30px" }}>
      <div onClick={() => push({ s: "sys.storage" })}><span className="ico">🔋</span><span>REŽIM ÚLOŽIŠTĚ<small>self-use, strop exportu, rezerva</small></span></div>
      <div onClick={() => push({ s: "sys.battery" })}><span className="ico">🧱</span><span>NASTAVENÍ BATERIE<small>bloky, kapacita, limity</small></span></div>
      <div onClick={() => push({ s: "sys.basic" })}><span className="ico">🕒</span><span>ZÁKLADNÍ NASTAVENÍ<small>čas, lokalita, verze</small></span></div>
      <div onClick={() => push({ s: "sys.smart" })}><span className="ico">🔌</span><span>CHYTRÉ VÝSTUPY<small>spotřebiče, TČ, wallbox</small></span></div>
      <div onClick={() => push({ s: "sys.grid" })}><span className="ico">🗼</span><span>PŘIPOJENÍ K SÍTI<small>jistič, fáze, limit exportu</small></span></div>
      <div onClick={() => push({ s: "sys.more" })}><span className="ico">➕</span><span>DALŠÍ FUNKCE<small>plánovač, pravidla, auta, test baterie</small></span></div>
    </div>
  );
}

const Foot = ({ children }) => <div className="foot">{children}</div>;
const HistBtn = ({ kind, push, label }) => <button type="button" onClick={() => push({ s: "hist", kind, per: "day" })}>📊 {label} = ‹ ENTER ›</button>;

// ---------- PV ----------
function PvTab({ d, v, push }) {
  const mppt = [1, 2, 3, 4].map((i) => ({ i, u: v(`pv_voltage_${i}`), a: v(`pv_current_${i}`) })).filter((x) => x.u != null || x.a != null);
  return (
    <div>
      <div className="hdr">Výkon FVE: {kW(d.pv_w)} <span>· dnes {kwh(d.today_kwh)} · celkem {kwh(v("energy_pv_total"), 0)}</span></div>
      <table>
        <thead><tr><th></th><th>Napětí</th><th>Proud</th><th>Výkon</th></tr></thead>
        <tbody>
          {mppt.length ? mppt.map((x) => (
            <tr key={x.i}><td className="l">MPPT{x.i}</td><td className="v">{num(x.u, 1)} V</td><td className="v">{num(x.a, 1)} A</td><td className="v">{x.u != null && x.a != null ? `${Math.round(x.u * x.a)} W` : "—"}</td></tr>))
            : <tr><td className="l" colSpan={4} style={{ color: "#44556a" }}>Hodnoty MPPT se čtou jen v diagnostickém okně (Moduly → 🔬 diagnostika MPPT).</td></tr>}
          <tr><td className="l">Celkem DC</td><td></td><td></td><td className="v">{Math.round(d.pv_w || 0)} W</td></tr>
          <tr><td className="l">AC výkon měniče</td><td></td><td></td><td className="v">{v("inverter_ac_power") != null ? `${Math.round(v("inverter_ac_power"))} W` : "—"}</td></tr>
          <tr><td className="l">Teplota měniče</td><td></td><td></td><td className="v">{v("temperature") != null ? `${num(v("temperature"), 1)} °C` : "—"}</td></tr>
        </tbody>
      </table>
      {(d.pv_forecast_days || []).length > 0 && (
        <div className="hdr" style={{ marginTop: 16 }}>Predikce: <span>{d.pv_forecast_days.map((f) => `${new Date(f.day).toLocaleDateString("cs-CZ", { weekday: "short" })} ${Math.round(f.kwh)} kWh`).join(" · ")}</span></div>)}
      <Foot><HistBtn kind="pv" push={push} label="Historie výroby" /></Foot>
    </div>
  );
}

// ---------- BATT ----------
function BattTab({ d, v, blocks, en, locId, has, push }) {
  const packs = [1, 2].filter((i) => d[`battery_soc_${i}`] != null || v(`battery_voltage_${i}`) != null);
  const blk = (i) => blocks.find((b) => b.idx === i);
  const enb = (i) => en?.blocks?.find((b) => b.idx === i);
  const rows = [
    ["Model", (i) => blk(i)?.module_model ? `${blk(i).modules_count ? blk(i).modules_count + "× " : ""}${blk(i).module_model}` : "—"],
    ["Napětí", (i) => (v(`battery_voltage_${i}`) != null ? `${num(v(`battery_voltage_${i}`), 1)} V` : "—")],
    ["Proud", (i) => (v(`battery_current_${i}`) != null ? `${num(v(`battery_current_${i}`), 1)} A` : "—")],
    ["Výkon", (i) => (d[`battery_w_${i}`] != null ? `${Math.round(d[`battery_w_${i}`])} W` : "—")],
    ["SoC", (i) => (d[`battery_soc_${i}`] != null ? `${Math.round(d[`battery_soc_${i}`])} %` : "—")],
    ["SoH (BMS)", (i) => (v(`battery_soh_${i}`) != null ? `${Math.round(v(`battery_soh_${i}`))} %` : "—")],
    ["Teplota", (i) => (v(`battery_temp_${i}`) != null ? `${num(v(`battery_temp_${i}`), 1)} °C` : "—")],
    ["Článek min / max", (i) => (v(`battery_cell_vmin_${i}`) != null ? `${num(v(`battery_cell_vmin_${i}`), 3)} / ${num(v(`battery_cell_vmax_${i}`), 3)} V` : "—")],
    ["Jmenovitá kapacita", (i) => (blk(i)?.capacity_kwh != null ? kwh(blk(i).capacity_kwh, 2) : "—")],
    ["Využitelné teď (test)", (i) => (enb(i)?.kwh_usable != null ? `${num(enb(i).kwh_usable, 2)} / ${num(enb(i).kwh_full, 2)} kWh` : "—")],
  ];
  return (
    <div>
      <div className="hdr">Nabíjení » dnes {kwh(v("energy_bat_charge_today"))} <span>/ celkem {kwh(v("energy_bat_charge_total"), 0)}</span>
        &nbsp;&nbsp;&nbsp; Vybíjení » dnes {kwh(v("energy_bat_discharge_today"))} <span>/ celkem {kwh(v("energy_bat_discharge_total"), 0)}</span></div>
      <table>
        <thead><tr><th></th>{packs.map((i) => <th key={i}>Baterie {i}</th>)}<th>Celkem</th></tr></thead>
        <tbody>
          {rows.map(([l, f]) => <tr key={l}><td className="l">{l}</td>{packs.map((i) => <td key={i} className="v">{f(i)}</td>)}
            <td className="v">{l === "SoC" ? `${d.soc != null ? Math.round(d.soc) : "—"} %` : l === "Výkon" ? `${Math.round(d.battery_w || 0)} W` : l === "Využitelné teď (test)" && en ? `${num(en.total_usable_kwh, 2)} / ${num(en.total_full_kwh, 2)} kWh` : l === "Jmenovitá kapacita" && blocks.length ? kwh(blocks.reduce((s, b) => s + Number(b.capacity_kwh || 0), 0), 2) : ""}</td></tr>)}
        </tbody>
      </table>
      <Foot><HistBtn kind="batt" push={push} label="Historie nabíjení a vybíjení" />{has("control") && locId ? <BatteryTestButton locId={locId} compact /> : null}</Foot>
    </div>
  );
}

// ---------- GRID ----------
function GridTab({ d, v, cfg, push }) {
  const L = [1, 2, 3];
  const u = (i) => v(`grid_voltage_l${i}`), a = (i) => v(`inverter_current_l${i}`);
  return (
    <div>
      <div className="hdr">Nákup » dnes {kwh(v("energy_import_today") ?? d.import_kwh)} <span>/ celkem {kwh(v("energy_import_total"), 0)}</span>
        &nbsp;&nbsp;&nbsp; Prodej » dnes {kwh(v("energy_export_today") ?? d.export_kwh)} <span>/ celkem {kwh(v("energy_export_total"), 0)}</span></div>
      <table>
        <thead><tr><th></th><th colSpan={3} style={{ textAlign: "center" }}>Měnič</th><th style={{ textAlign: "center" }}>Elektroměr</th></tr>
          <tr><th></th>{L.map((i) => <th key={i}>L{i}</th>)}<th>celkem</th></tr></thead>
        <tbody>
          <tr><td className="l">Napětí</td>{L.map((i) => <td key={i} className="v">{u(i) != null ? `${num(u(i), 1)} V` : "—"}</td>)}<td></td></tr>
          <tr><td className="l">Proud</td>{L.map((i) => <td key={i} className="v">{a(i) != null ? `${num(a(i), 1)} A` : "—"}</td>)}<td></td></tr>
          <tr><td className="l">Zdánlivý výkon</td>{L.map((i) => <td key={i} className="v">{u(i) != null && a(i) != null ? `${Math.round(u(i) * a(i))} VA` : "—"}</td>)}<td className="v">{d.grid_w != null ? `${d.grid_w > 0 ? "+" : ""}${Math.round(d.grid_w)} W` : "—"}</td></tr>
          <tr><td className="l">Činný výkon měniče</td><td className="v" colSpan={3}>{v("inverter_ac_power") != null ? `${Math.round(v("inverter_ac_power"))} W` : "—"}</td><td className="v">{d.grid_w != null ? (d.grid_w > 50 ? "odběr" : d.grid_w < -50 ? "dodávka" : "vyrovnáno") : ""}</td></tr>
          <tr><td className="l">Strop exportu (TERA)</td><td className="v" colSpan={4}>{cfg?.grid_export_limit_kw != null ? `${num(cfg.grid_export_limit_kw, 1)} kW` : "—"}</td></tr>
        </tbody>
      </table>
      <p style={{ fontSize: 12, color: "#44556a", marginTop: 10 }}>Znaménko elektroměru: + odběr ze sítě, − dodávka do sítě.</p>
      <Foot><HistBtn kind="grid" push={push} label="Historie nákupu a prodeje" /></Foot>
    </div>
  );
}

// ---------- LOAD ----------
function LoadTab({ d, v, push }) {
  const L = [1, 2, 3];
  return (
    <div>
      <div className="hdr">Spotřeba dnes {kwh(d.cons_today_kwh)} <span>/ celkem (měnič) {kwh(v("energy_load_total"), 0)}</span></div>
      <table>
        <thead><tr><th></th><th>Dům (bilance)</th><th>Dům dle měniče</th><th>Záloha (backup)</th></tr></thead>
        <tbody>
          <tr><td className="l">Výkon</td><td className="v">{Math.round(d.load_w || 0)} W</td><td className="v">{v("house_load") != null ? `${Math.round(v("house_load"))} W` : "—"}</td><td className="v">{v("backup_load_power") != null ? `${Math.round(v("backup_load_power"))} W` : "—"}</td></tr>
          {L.map((i) => <tr key={i}><td className="l">Záloha L{i}</td><td></td><td></td><td className="v">{v(`backup_voltage_l${i}`) != null ? `${num(v(`backup_voltage_l${i}`), 1)} V · ${num(v(`backup_current_l${i}`), 1)} A` : "—"}</td></tr>)}
        </tbody>
      </table>
      <p style={{ fontSize: 12, color: "#44556a", marginTop: 10 }}>Dům (bilance) = FVE + síť − baterie; spotřeba není měřena přímo.</p>
      <Foot><HistBtn kind="load" push={push} label="Historie spotřeby" /></Foot>
    </div>
  );
}

// ---------- MORE ----------
function MoreTab({ v, m, devs, solis, push }) {
  const dev = devs.find((x) => x.device_id === solis) || {};
  const last = m.battery_soc?.time || m.pv_power?.time;
  const age = last ? Math.round((Date.now() - new Date(last).getTime()) / 1000) : null;
  const rows = [
    ["Výroba FVE", v("energy_today"), v("energy_pv_total")],
    ["Nabito do baterie", v("energy_bat_charge_today"), v("energy_bat_charge_total")],
    ["Vybito z baterie", v("energy_bat_discharge_today"), v("energy_bat_discharge_total")],
    ["Odběr ze sítě", v("energy_import_today"), v("energy_import_total")],
    ["Dodávka do sítě", v("energy_export_today"), v("energy_export_total")],
    ["Spotřeba domu", v("energy_load_today"), v("energy_load_total")],
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
      <div>
        <div className="hdr">Měnič <span>· {dev.name || solis}</span></div>
        <div className="kv">
          <span>Modul</span><span>{solis}</span>
          <span>Adaptér</span><span>{dev.adapter || "—"}</span>
          <span>Stav</span><span>{v("inverter_state") != null ? `${STATE_TXT[v("inverter_state")] || "kód"} (${v("inverter_state")})` : "—"}</span>
          <span>Porucha (slovo)</span><span>{v("inverter_fault") != null ? String(v("inverter_fault")) : "—"}</span>
          <span>Teplota měniče</span><span>{v("temperature") != null ? `${num(v("temperature"), 1)} °C` : "—"}</span>
          <span>Poslední vzorek</span><span>{age != null ? `před ${age} s` : "—"}</span>
          <span>Čte</span><span>{dev.emsbox_id ? `EMSBOX č. ${dev.emsbox_id}` : "server"}</span>
        </div>
      </div>
      <div>
        <div className="hdr">Energie <span>· čítače měniče</span></div>
        <table style={{ fontSize: 14 }}>
          <thead><tr><th></th><th>Dnes</th><th>Celkem</th></tr></thead>
          <tbody>{rows.map(([l, a, b]) => <tr key={l}><td className="l">{l}</td><td className="v">{kwh(a)}</td><td className="v">{kwh(b, 0)}</td></tr>)}</tbody>
        </table>
      </div>
      <Foot><HistBtn kind="more" push={push} label="Historie energií" /></Foot>
    </div>
  );
}

// ---------- HISTORIE: sloupce den / měsíc / rok ----------
function HistoryScreen({ locId, kind, period, at, onAt }) {
  const [r, setR] = useState(null);
  const [err, setErr] = useState("");
  const def = HIST_DEF[kind] || HIST_DEF.pv;
  useEffect(() => { let alive = true; setR(null); setErr("");
    api.energyHistory(locId, period, at).then((x) => alive && setR(x)).catch((e) => alive && setErr(e.message));
    return () => { alive = false; }; }, [locId, period, at]);
  if (err) return <p style={{ color: "#a33" }}>{err}</p>;
  if (!r) return <p>Načítám…</p>;
  const rows = r.rows || [];
  const keys = def.series.map((s) => s[0]);
  const maxV = Math.max(1, ...rows.flatMap((x) => keys.map((k) => x[k] || 0)));
  const nice = (() => { const p = Math.pow(10, Math.floor(Math.log10(maxV))); const n = Math.ceil(maxV / p); return n * p; })();
  const CW = 900, CH = 380, L = 70, R = 20, T = 30, B = 40;
  const pw = CW - L - R, ph = CH - T - B;
  const n = rows.length || 1, gw = pw / n, bw = Math.max(2, (gw * 0.7) / keys.length);
  const y = (val) => T + ph * (1 - val / nice);
  const label = period === "day" ? `${new Date(`${r.at || new Date().toISOString().slice(0, 7)}-01`).toLocaleDateString("cs-CZ", { month: "long", year: "numeric" })}`
    : period === "month" ? (r.at || new Date().getFullYear()) : "celkem";
  const perTxt = period === "day" ? "Měsíčně" : period === "month" ? "Ročně" : "Celkem";
  return (
    <div>
      <div className="per">
        {period !== "year" && <button type="button" onClick={() => onAt(r.prev)}>‹</button>}
        <b style={{ minWidth: 150, textAlign: "center", textTransform: "capitalize" }}>{label}</b>
        {period !== "year" && <button type="button" onClick={() => onAt(r.next)}>›</button>}
        <span style={{ marginLeft: 14, color: "#44556a" }}>{perTxt}: {def.series.map((s) => `${s[1]} ${num(r.totals?.[s[0]], 1)} kWh`).join(" / ")}</span>
      </div>
      <svg viewBox={`0 0 ${CW} ${CH}`} width={CW} height={CH} style={{ display: "block" }}>
        <text x={L - 8} y={T - 12} textAnchor="end" fontSize="12" fill="#44556a">kWh</text>
        {[0, 0.2, 0.4, 0.6, 0.8, 1].map((f) => (
          <g key={f}><line x1={L} x2={CW - R} y1={y(nice * f)} y2={y(nice * f)} stroke="#c9d6e6" strokeWidth="0.8" />
            <text x={L - 8} y={y(nice * f) + 4} textAnchor="end" fontSize="12" fill="#44556a">{num(nice * f, nice < 10 ? 1 : 0)}</text></g>))}
        {rows.map((row, i) => (
          <g key={row.label}>
            {keys.map((k, j) => {
              const val = row[k] || 0; const x = L + i * gw + (gw - bw * keys.length) / 2 + j * bw;
              return <rect key={k} x={x} y={y(val)} width={bw - 1} height={Math.max(0, y(0) - y(val))} fill={def.series[j][2]} rx={1}><title>{`${row.label}: ${def.series[j][1]} ${num(val, 1)} kWh`}</title></rect>;
            })}
            {(n <= 16 || i % Math.ceil(n / 16) === 0) && <text x={L + i * gw + gw / 2} y={CH - B + 16} textAnchor="middle" fontSize="12" fill="#44556a">{row.label}</text>}
          </g>))}
        <line x1={L} x2={CW - R} y1={y(0)} y2={y(0)} stroke="#4a5a6e" strokeWidth="1" />
      </svg>
      <div style={{ display: "flex", gap: 18, fontSize: 13, color: "#44556a", paddingLeft: 70 }}>
        {def.series.map((s) => <span key={s[0]}><span style={{ display: "inline-block", width: 12, height: 12, background: s[2], marginRight: 5, verticalAlign: "middle" }} />{s[1]}</span>)}
        <span style={{ marginLeft: "auto", paddingRight: 20 }}>{period === "day" ? "dny v měsíci" : period === "month" ? "měsíce" : "roky"} · z denních čítačů měniče</span>
      </div>
    </div>
  );
}

// ---------- VÝSTRAHY ----------
function AlarmsScreen({ locId }) {
  const [a, setA] = useState(null);
  useEffect(() => { let alive = true; api.alerts().then((r) => alive && setA((r.alerts || []).filter((x) => x.locality_id == null || x.locality_id === locId))).catch(() => alive && setA([]));
    return () => { alive = false; }; }, [locId]);
  if (!a) return <p>Načítám…</p>;
  return (
    <div>
      <div className="hdr">Aktivní výstrahy a události <span>· {a.length}</span></div>
      {a.length === 0 && <p style={{ color: "#2d8a3e", fontSize: 15 }}>✓ Žádné výstrahy.</p>}
      <table style={{ fontSize: 14 }}>
        <tbody>{a.slice(0, 11).map((x) => (
          <tr key={x.id}><td className="l">{x.start ? new Date(x.start).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</td>
            <td className="v" style={{ color: x.severity === "warning" ? "#b4541a" : x.severity === "critical" ? "#a33" : "inherit" }}>{x.title}</td>
            <td className="l" style={{ whiteSpace: "normal", maxWidth: 480 }}>{x.detail}</td></tr>))}
        </tbody>
      </table>
      <p style={{ fontSize: 12, color: "#44556a", marginTop: 10 }}>Kompletní seznam a historie: zvoneček 🔔 v záhlaví TERA.</p>
    </div>
  );
}

// ---------- NASTAVENÍ (přehled hodnot + odkazy do TERA; samotné řízení je v Řízení/Lokality/Moduly) ----------
function StorageMode({ cfg, d }) {
  const yn = (b) => (b ? "✓ zapnuto" : "✗ vypnuto");
  return (
    <div>
      <div className="hdr">Režim úložiště <span>· plánovač TERA</span></div>
      <div className="kv">
        <span>Režim</span><span>{cfg.enabled ? "Self-Use + plánovač" : "Self-Use (plánovač vypnut)"}</span>
        <span>Plánovač</span><span>{yn(cfg.enabled)}</span>
        <span>Nabíjení ze sítě (levné hodiny)</span><span>{yn(cfg.grid_charge_enabled)}</span>
        <span>Nabíjení při záporné ceně</span><span>{yn(cfg.neg_price_charge_enabled)}{cfg.neg_price_charge_enabled ? ` (práh ${cfg.neg_price_threshold_czk} Kč/kWh)` : ""}</span>
        <span>Vybíjení do sítě</span><span>{yn(cfg.allow_grid_discharge)}</span>
        <span>Strop exportu</span><span>{cfg.grid_export_limit_kw != null ? `${num(cfg.grid_export_limit_kw, 1)} kW` : "—"}</span>
        <span>Rezerva baterie (podlaha SoC)</span><span>{cfg.soc_min_pct != null ? `${cfg.soc_min_pct} %` : "—"}</span>
        <span>Max nabíjení / vybíjení</span><span>{cfg.max_charge_kw != null ? `${cfg.max_charge_kw} / ${cfg.max_discharge_kw} kW` : "—"}</span>
        <span>Kapacita (jmenovitá)</span><span>{cfg.capacity_kwh != null ? kwh(cfg.capacity_kwh, 1) : "—"}</span>
        <span>SoC teď</span><span>{d.soc != null ? `${Math.round(d.soc)} %` : "—"}</span>
      </div>
      <Foot><Link to="/control" className="ebtn">Upravit v Řízení</Link></Foot>
    </div>
  );
}

function BatterySetting({ blocks, en, v }) {
  return (
    <div>
      <div className="hdr">Bateriové bloky <span>· {blocks.length ? `${blocks.length} bloky` : "nezadané — kapacita se dělí rovnoměrně"}</span></div>
      <table style={{ fontSize: 14 }}>
        <thead><tr><th>blok</th><th>moduly</th><th>jmenovitá</th><th>instalace</th><th>SoH (BMS)</th><th>využitelná (test)</th></tr></thead>
        <tbody>{(blocks.length ? blocks : [{ idx: 1, name: "B1" }, { idx: 2, name: "B2" }]).map((b) => {
          const e = en?.blocks?.find((x) => x.idx === b.idx);
          return <tr key={b.idx}><td className="v">{b.name}</td><td className="l">{b.modules_count ? `${b.modules_count}× ${b.module_model || ""}` : "—"}</td><td className="v">{b.capacity_kwh != null ? kwh(b.capacity_kwh, 2) : "—"}</td>
            <td className="l">{b.installed || "—"}</td><td className="v">{v(`battery_soh_${b.idx}`) != null ? `${Math.round(v(`battery_soh_${b.idx}`))} %` : "—"}</td><td className="v">{e?.kwh_full != null ? `${num(e.kwh_full, 2)} kWh (test #${en.test_id})` : "—"}</td></tr>; })}
        </tbody>
      </table>
      <div className="kv" style={{ marginTop: 14 }}>
        <span>Limit nabíjecího / vybíjecího proudu (měnič)</span><span>{v("charge_current_limit") != null ? `${num(v("charge_current_limit"), 1)} / ${num(v("discharge_current_limit"), 1)} A` : "—"}</span>
        <span>Záložní SoC (43024)</span><span>{v("backup_soc") != null ? `${Math.round(v("backup_soc"))} %` : "—"}</span>
      </div>
      <Foot><Link to="/modules" className="ebtn">Bloky v Modulech</Link></Foot>
    </div>
  );
}

function BasicSetting({ now, name, locId, devs }) {
  const [ver, setVer] = useState(null);
  useEffect(() => { fetch("/api/version").then((r) => r.json()).then((r) => setVer(r?.version)).catch(() => {}); }, []);
  return (
    <div>
      <div className="hdr">Základní nastavení</div>
      <div className="kv">
        <span>Čas (prohlížeč)</span><span>{now.toLocaleString("cs-CZ")}</span>
        <span>Časové pásmo</span><span>{Intl.DateTimeFormat().resolvedOptions().timeZone}</span>
        <span>Lokalita</span><span>{name} (ID {locId})</span>
        <span>Zařízení</span><span>{devs.map((x) => `${x.name || x.device_id}`).join(", ")}</span>
        <span>TERA EMS</span><span>{ver ? `v${ver}` : "—"}</span>
      </div>
      <Foot><Link to="/localities" className="ebtn">Lokality</Link><Link to="/vzhled" className="ebtn">Vzhled a rozhraní</Link></Foot>
    </div>
  );
}

function SmartPort({ devs, locId }) {
  const [outs, setOuts] = useState(null);
  useEffect(() => { let alive = true; api.listOutputs().then((r) => alive && setOuts((r || []).filter((o) => o.locality_id == null || o.locality_id === locId))).catch(() => alive && setOuts([]));
    return () => { alive = false; }; }, [locId]);
  const hp = devs.find((x) => x.adapter === "stiebel_isg"), ev = devs.find((x) => x.adapter === "goe_charger");
  return (
    <div>
      <div className="hdr">Chytré výstupy a spotřebiče</div>
      <table style={{ fontSize: 14 }}>
        <thead><tr><th>výstup</th><th>stav</th><th>poslední rozhodnutí</th></tr></thead>
        <tbody>
          {(outs || []).map((o) => <tr key={o.id}><td className="v">{o.name}</td><td className="v" style={{ color: o.is_on ? "#2d8a3e" : "#44556a" }}>{o.is_on ? "● sepnuto" : "○ rozepnuto"}</td><td className="l" style={{ whiteSpace: "normal", maxWidth: 520 }}>{o.last_decision || "—"}</td></tr>)}
          {hp && <tr><td className="v">🌀 {hp.name || hp.device_id}</td><td className="l">tepelné čerpadlo</td><td className="l">řízení přes ISG (Stiebel)</td></tr>}
          {ev && <tr><td className="v">🚗 {ev.name || ev.device_id}</td><td className="l">wallbox</td><td className="l">go-e, lokální API</td></tr>}
          {outs && !outs.length && !hp && !ev && <tr><td colSpan={3} className="l">Žádné výstupy.</td></tr>}
        </tbody>
      </table>
      <Foot><Link to="/automation" className="ebtn">Automatizace</Link>{hp && <Link to="/heatpump" className="ebtn">Tepelné čerpadlo</Link>}</Foot>
    </div>
  );
}

function GridPort({ cfg, v, locId }) {
  const [loc, setLoc] = useState(null);
  useEffect(() => { api.listLocalities?.().then?.((ls) => setLoc((ls || []).find((l) => l.id === locId) || null)).catch?.(() => {}); }, [locId]);
  return (
    <div>
      <div className="hdr">Připojení k síti</div>
      <div className="kv">
        <span>Hlavní jistič</span><span>{loc?.main_breaker_a ? `${loc.main_breaker_phases || 3}× ${loc.main_breaker_a} A` : "— (zadej v Lokalitě)"}</span>
        <span>Strop exportu (TERA)</span><span>{cfg.grid_export_limit_kw != null ? `${num(cfg.grid_export_limit_kw, 1)} kW` : "—"}</span>
        <span>Napětí L1 / L2 / L3</span><span>{[1, 2, 3].map((i) => (v(`grid_voltage_l${i}`) != null ? num(v(`grid_voltage_l${i}`), 1) : "—")).join(" / ")} V</span>
        <span>Výkon na elektroměru</span><span>{kW(v("grid_power"))} ({v("grid_power") > 50 ? "odběr" : v("grid_power") < -50 ? "dodávka" : "vyrovnáno"})</span>
        <span>EAN / adresa</span><span>{loc?.address || "—"}</span>
      </div>
      <Foot><Link to="/localities" className="ebtn">Lokality</Link></Foot>
    </div>
  );
}

function MoreFunction({ has }) {
  const items = [["/control", "🧠 Plánovač a ruční řízení"], ["/automation", "⏰ Časová a spotová pravidla"], ["/cars", "🚘 Auta (BMW CarData)"], ["/heatpump", "🌀 Tepelné čerpadlo"], ["/vzhled", "🎨 Vzhled a rozhraní"]];
  return (
    <div className="menu" style={{ padding: "10px 50px", gap: "10px 24px" }}>
      {items.map(([to, l]) => <Link key={to} to={to} style={{ textDecoration: "none" }}><div>{l}</div></Link>)}
      {has("control") && <div style={{ background: "#e3eefb" }}>🧪 Test baterie — v INFORMACE O ELEKTRÁRNĚ → BATT</div>}
    </div>
  );
}

function ProSetting({ has, solis }) {
  if (!has("admin")) return <p style={{ fontSize: 15 }}>Servisní nastavení je dostupné jen správci. Rozhraní dashboardu si můžeš změnit ve <Link to="/vzhled">Vzhledu</Link>.</p>;
  const items = [["/modules", "🧩 Moduly a adaptéry"], [`/diagnostics/${solis}`, "🔬 Diagnostika modulu"], ["/emsboxes", "📦 EMSBOXy"], ["/users", "👥 Uživatelé a role"], ["/data-diag", "🗄 Diagnostika dat"], ["/localities", "📍 Lokality"]];
  return (
    <div className="menu" style={{ padding: "10px 50px", gap: "10px 24px" }}>
      {items.map(([to, l]) => <Link key={to} to={to} style={{ textDecoration: "none" }}><div>{l}</div></Link>)}
    </div>
  );
}
