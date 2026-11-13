// 📟 Rozhraní „Panel měniče (LCD)“ — alternativní dashboard ve stylu displeje střídače (zadání 13. 11. 2026, alternativnirozhrani01.pdf).
// Stejná data jako schéma TERA (aggregate-now, latest metriky Solisu, bloky baterie, křivka z testu), jiná prezentace:
// modrá lišta se stavem a časem, záložky STAV · PV · BATT · GRID · LOAD · MORE · ENERGIE, tabulky hodnot po fázích, stavové schéma.
// Kreslí se ve virtuálním rozlišení 960×540 a škáluje na šířku kontejneru (mobil: zmenšené, na šířku i na výšku).
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { BatteryTestButton } from "./BatteryTest";

const W = 960, H = 540;
const TABS = [["status", "STAV"], ["pv", "PV"], ["batt", "BATT"], ["grid", "GRID"], ["load", "LOAD"], ["more", "MORE"], ["energy", "ENERGIE"]];
const STATE_TXT = { 15: "Normální", 3: "Výroba", 4121: "Alarm IGFOL-F (1019)", 0: "Čekání", 1: "Start", 2: "Start", 4: "Alarm", 5: "Chyba" };

const css = `
.lcd{position:relative;width:${W}px;height:${H}px;background:#eef3f9;color:#1b2a3a;font-family:Inter,Segoe UI,Arial,sans-serif;border-radius:8px;overflow:hidden;box-shadow:0 2px 14px rgba(0,0,0,.35);transform-origin:top left;user-select:none}
.lcd *{box-sizing:border-box}
.lcd .bar{height:44px;background:linear-gradient(#2c6fd1,#1d55b0);color:#fff;display:flex;align-items:center;padding:0 14px;gap:4px;font-size:15px;font-weight:600;letter-spacing:.3px}
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
.lcd .foot{position:absolute;left:0;right:0;bottom:12px;text-align:center}
.lcd .foot button{background:#cfe2f8;color:#1b2a3a;border:1px solid #9fc0ea;border-radius:6px;padding:6px 16px;font-size:13px;cursor:pointer}
.lcd .flow{stroke-dasharray:8 6;animation:lcdflow 1s linear infinite}
@keyframes lcdflow{to{stroke-dashoffset:-14}}
.lcd .menu{display:grid;grid-template-columns:1fr 1fr;gap:14px 28px;padding:10px 40px}
.lcd .menu div{background:#fff;border:1px solid #b8cde8;border-radius:8px;padding:16px 18px;font-size:16px;font-weight:600;color:#1d4f9c;cursor:pointer}
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

export function LcdLocality({ name, devs }) {
  const ids = devs.map((d) => d.device_id);
  const locId = devs[0].locality_id;
  const solis = devs.find((d) => d.adapter === "solis")?.device_id || ids[0];
  const [tab, setTab] = useState(() => localStorage.getItem("lcd.tab") || "status");
  const [d, setD] = useState(null);           // aggregate-now
  const [m, setM] = useState({});             // latest metriky Solisu
  const [blocks, setBlocks] = useState([]);
  const [en, setEn] = useState(null);
  const [cfg, setCfg] = useState({});
  const [now, setNow] = useState(new Date());
  const wrap = useRef(null);
  const scale = useScale(wrap);
  const { has } = useAuth();
  useEffect(() => { localStorage.setItem("lcd.tab", tab); }, [tab]);
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

  const body = (() => {
    if (!d) return <p style={{ padding: 20 }}>Načítám…</p>;
    switch (tab) {
      case "pv": return <PvTab d={d} v={v} />;
      case "batt": return <BattTab d={d} v={v} blocks={blocks} en={en} locId={locId} canTest={has("control")} />;
      case "grid": return <GridTab d={{ ...d, export_limit_kw: cfg.grid_export_limit_kw }} v={v} />;
      case "load": return <LoadTab d={d} v={v} />;
      case "more": return <MoreTab d={d} v={v} m={m} devs={devs} solis={solis} />;
      case "energy": return <EnergyTab v={v} d={d} />;
      default: return <StatusTab d={d} v={v} en={en} />;
    }
  })();

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
            <span style={{ marginRight: 10, color: stBad ? "#ffd3d3" : "#fff" }}>Stav: {stTxt}</span>
            {TABS.map(([k, l]) => <span key={k} className={`tab${tab === k ? " on" : ""}`} onClick={() => setTab(k)}>{l}</span>)}
            <span className="clock">{dt}</span>
          </div>
          <div className="body">{body}</div>
        </div>
      </div>
    </section>
  );
}

// ---------- STAV: schéma toku ve stylu displeje ----------
function StatusTab({ d, v, en }) {
  const pv = d.pv_w || 0, bat = d.battery_w || 0, grid = d.grid_w || 0, load = d.load_w || 0, bk = d.backup_w || 0;
  const on = (w) => Math.abs(w) > 50;
  const soc1 = d.battery_soc_1, soc2 = d.battery_soc_2;
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
  const kwhOf = (i) => en?.blocks?.find((b) => b.idx === i)?.kwh_usable;
  const Arrow = ({ d: path, w, rev, label, lx, ly, color = "#e08a1e" }) => (
    <g>
      <path d={path} fill="none" stroke="#9fb3c8" strokeWidth="6" strokeLinecap="round" />
      {on(w) && <path d={path} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" className="flow" style={rev ? { animationDirection: "reverse" } : undefined} />}
      <text x={lx} y={ly} textAnchor="middle" fontSize="15" fontWeight="600" fill="#1b2a3a">{label}</text>
    </g>);
  return (
    <svg viewBox="0 0 916 470" width="916" height="470" style={{ display: "block" }}>
      {/* FVE */}
      <g transform="translate(40,70)">
        <polygon points="0,60 90,60 120,0 30,0" fill="#2f6fd0" stroke="#163f80" strokeWidth="2" />
        {[1, 2].map((i) => <line key={i} x1={30 - i * 0 + i * 0} y1={i * 20} x2={120 - i * 0} y2={i * 20} stroke="#163f80" strokeWidth="1" transform={`translate(${-i * 10},0)`} />)}
        {[30, 60, 90].map((x) => <line key={x} x1={x} y1={0} x2={x - 30} y2={60} stroke="#163f80" strokeWidth="1" />)}
        <text x={60} y={85} textAnchor="middle" fontSize="12" fill="#44556a">FVE</text>
      </g>
      <Arrow d="M170,100 L330,100" w={pv} label={kW(pv)} lx={250} ly={88} />
      {/* měnič */}
      <rect x={330} y={60} width={130} height={200} rx={6} fill="#fff" stroke="#4a5a6e" strokeWidth="2" />
      <rect x={365} y={110} width={60} height={34} rx={4} fill="#dfe8f4" stroke="#9fb3c8" />
      <text x={395} y={240} textAnchor="middle" fontSize="12" fill="#44556a">měnič</text>
      {/* baterie */}
      <Bat x={60} soc={soc1} volt={v("battery_voltage_1")} kwhU={kwhOf(1)} n={1} />
      <Bat x={130} soc={soc2} volt={v("battery_voltage_2")} kwhU={kwhOf(2)} n={2} />
      <text x={200} y={325} fontSize="12" fill={v("battery_cell_vmin_1") != null ? "#2d8a3e" : "#a33"}>BMS 1 {v("battery_cell_vmin_1") != null ? "OK" : "—"}</text>
      <text x={200} y={345} fontSize="12" fill={v("battery_cell_vmin_2") != null ? "#2d8a3e" : "#a33"}>BMS 2 {v("battery_cell_vmin_2") != null ? "OK" : "—"}</text>
      <Arrow d="M330,220 L250,220 L250,300" w={bat} rev={bat < 0} label={`${bat > 50 ? "▲ nabíjení" : bat < -50 ? "▼ vybíjení" : ""} ${kW(Math.abs(bat))}`} lx={250} ly={206} color={bat >= 0 ? "#3bb54a" : "#e08a1e"} />
      {/* dům */}
      <Arrow d="M460,100 L600,100" w={load} label={kW(load)} lx={530} ly={88} />
      <g transform="translate(600,60)">
        <polygon points="0,40 45,5 90,40" fill="#d9534f" />
        <rect x={10} y={40} width={70} height={45} fill="#fff" stroke="#4a5a6e" strokeWidth="2" />
        <rect x={38} y={58} width={16} height={27} fill="#4a5a6e" />
        <text x={45} y={105} textAnchor="middle" fontSize="12" fill="#44556a">dům</text>
      </g>
      {/* záloha / backup */}
      <Arrow d="M460,180 L600,180" w={bk} label={bk > 50 ? kW(bk) : "0,00 kW"} lx={530} ly={168} color="#39a0c5" />
      <g transform="translate(610,150)">
        <circle cx={30} cy={28} r={22} fill="#fff" stroke="#4a5a6e" strokeWidth="2" />
        <path d="M22,40 L38,40 L38,50 L22,50 Z" fill="#4a5a6e" />
        <path d="M30,10 L30,24 M20,16 L24,24 M40,16 L36,24" stroke="#e0a020" strokeWidth="2" />
        <text x={30} y={70} textAnchor="middle" fontSize="12" fill="#44556a">záloha</text>
      </g>
      {/* síť */}
      <Arrow d="M460,250 L760,250" w={grid} rev={grid < 0} label={`${grid > 50 ? "◀ odběr" : grid < -50 ? "dodávka ▶" : ""} ${kW(Math.abs(grid))}`} lx={610} ly={272} color="#e0a020" />
      <g transform="translate(770,200)">
        <path d="M30,0 L10,100 M30,0 L50,100 M0,100 L60,100 M14,40 L46,40 M10,65 L50,65 M18,20 L42,20" stroke="#4a5a6e" strokeWidth="2.5" fill="none" />
        <text x={30} y={120} textAnchor="middle" fontSize="12" fill="#44556a">síť</text>
      </g>
      {/* souhrn dne */}
      <g fontSize="14" fill="#1b2a3a">
        <text x={330} y={310}>Výroba dnes: <tspan fontWeight="600">{kwh(d.today_kwh)}</tspan></text>
        <text x={330} y={332}>Nákup dnes: <tspan fontWeight="600">{kwh(d.import_kwh)}</tspan> · Prodej dnes: <tspan fontWeight="600">{kwh(d.export_kwh)}</tspan></text>
        <text x={330} y={354}>Spotřeba dnes: <tspan fontWeight="600">{kwh(d.cons_today_kwh)}</tspan></text>
        {en && <text x={330} y={376}>Využitelné v baterii: <tspan fontWeight="600" fill="#2457a8">{num(en.total_usable_kwh, 1)} kWh</tspan> <tspan fill="#44556a">(do {en.floor_pct ?? 10} %, test #{en.test_id})</tspan></text>}
        {d.xcheck?.battery_power_inv != null && <text x={330} y={402} fontSize="12" fill="#44556a">měnič hlásí baterii {kW(d.xcheck.battery_power_inv)} · dům {d.xcheck.house_load_inv != null ? kW(d.xcheck.house_load_inv) : "—"}</text>}
      </g>
    </svg>
  );
}

// ---------- PV ----------
function PvTab({ d, v }) {
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
    </div>
  );
}

// ---------- BATT ----------
function BattTab({ d, v, blocks, en, locId, canTest }) {
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
      <div className="foot">{canTest && locId ? <BatteryTestButton locId={locId} compact /> : <span style={{ fontSize: 12, color: "#44556a" }}>Historie nabíjení a test baterie — v detailu baterie (Schéma TERA)</span>}</div>
    </div>
  );
}

// ---------- GRID ----------
function GridTab({ d, v }) {
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
          <tr><td className="l">Strop exportu</td><td className="v" colSpan={4}>{d.export_limit_kw != null ? `${num(d.export_limit_kw, 1)} kW` : "—"}</td></tr>
        </tbody>
      </table>
      <p style={{ fontSize: 12, color: "#44556a", marginTop: 14 }}>Znaménko elektroměru: + odběr ze sítě, − dodávka do sítě (registr 33130, EMS otáčí znaménko).</p>
    </div>
  );
}

// ---------- LOAD ----------
function LoadTab({ d, v }) {
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
      <p style={{ fontSize: 12, color: "#44556a", marginTop: 14 }}>Dům (bilance) = FVE + síť − baterie; spotřeba není měřena přímo.</p>
    </div>
  );
}

// ---------- MORE ----------
function MoreTab({ d, v, m, devs, solis }) {
  const dev = devs.find((x) => x.device_id === solis) || {};
  const last = m.battery_soc?.time || m.pv_power?.time;
  const age = last ? Math.round((Date.now() - new Date(last).getTime()) / 1000) : null;
  return (
    <div>
      <div className="hdr">Měnič <span>· {dev.name || solis}</span></div>
      <table>
        <tbody>
          <tr><td className="l">Modul</td><td className="v">{solis}</td></tr>
          <tr><td className="l">Adaptér</td><td className="v">{dev.adapter || "—"}</td></tr>
          <tr><td className="l">Stav měniče</td><td className="v">{v("inverter_state") != null ? `${STATE_TXT[v("inverter_state")] || "kód"} (${v("inverter_state")})` : "—"}</td></tr>
          <tr><td className="l">Porucha (slovo)</td><td className="v">{v("inverter_fault") != null ? String(v("inverter_fault")) : "—"}</td></tr>
          <tr><td className="l">Teplota měniče</td><td className="v">{v("temperature") != null ? `${num(v("temperature"), 1)} °C` : "—"}</td></tr>
          <tr><td className="l">Poslední vzorek</td><td className="v">{age != null ? `před ${age} s` : "—"}</td></tr>
          <tr><td className="l">Čte</td><td className="v">{dev.emsbox_id ? `EMSBOX č. ${dev.emsbox_id}` : "server"}</td></tr>
          <tr><td className="l">Ostatní zařízení lokality</td><td className="v">{devs.filter((x) => x.device_id !== solis).map((x) => `${x.name || x.device_id} (${x.adapter})`).join(", ") || "—"}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

// ---------- ENERGIE (čítače měniče; grafy měsíc/rok/celkem přijdou v dalším kroku) ----------
function EnergyTab({ v, d }) {
  const rows = [
    ["Výroba FVE", v("energy_today") ?? d.today_kwh, v("energy_pv_total")],
    ["Nabito do baterie", v("energy_bat_charge_today"), v("energy_bat_charge_total")],
    ["Vybito z baterie", v("energy_bat_discharge_today"), v("energy_bat_discharge_total")],
    ["Odběr ze sítě", v("energy_import_today") ?? d.import_kwh, v("energy_import_total")],
    ["Dodávka do sítě", v("energy_export_today") ?? d.export_kwh, v("energy_export_total")],
    ["Spotřeba domu", v("energy_load_today") ?? d.cons_today_kwh, v("energy_load_total")],
  ];
  return (
    <div>
      <div className="hdr">Energie <span>· čítače měniče</span></div>
      <table>
        <thead><tr><th></th><th>Dnes</th><th>Celkem</th></tr></thead>
        <tbody>{rows.map(([l, a, b]) => <tr key={l}><td className="l">{l}</td><td className="v">{kwh(a)}</td><td className="v">{kwh(b, 0)}</td></tr>)}</tbody>
      </table>
      <p style={{ fontSize: 12, color: "#44556a", marginTop: 14 }}>Sloupcové grafy MĚSÍC · ROK · CELKEM (jako na displeji) — další verze.</p>
    </div>
  );
}
