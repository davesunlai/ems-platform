import { useEffect, useState, useRef } from "react";
import { api } from "../api";
import TimeChart from "../components/TimeChart";
import MultiChart from "../components/MultiChart";
import ForecastChart from "../components/ForecastChart";
import TempChart from "../components/TempChart";
import BillingTable from "../components/BillingTable";
import Icon from "../components/Icon";
import { METRIC_LABEL as LABELS, iconFor, groupMetrics } from "../metrics";

const norm = (s) => (s || "").toString().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

function SearchSelect({ value, options, onChange, placeholder = "— vyber —", allowEmpty = false, emptyLabel }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const sel = options.find((o) => String(o.id) === String(value));
  const filtered = q ? options.filter((o) => norm(o.label).includes(norm(q))) : options;
  const item = { padding: "6px 10px", cursor: "pointer", fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };
  return (
    <div style={{ position: "relative" }}>
      <input
        value={open ? q : (sel ? sel.label : "")}
        placeholder={placeholder}
        onFocus={() => { setOpen(true); setQ(""); }}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && (
        <div style={{ position: "absolute", zIndex: 30, top: "100%", left: 0, right: 0, maxHeight: 240, overflowY: "auto",
          background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8, marginTop: 2, boxShadow: "0 8px 22px rgba(0,0,0,.45)" }}>
          {allowEmpty && (
            <div onMouseDown={() => { onChange(""); setOpen(false); }} style={{ ...item, color: "var(--muted)" }}>{emptyLabel || placeholder}</div>
          )}
          {filtered.map((o) => (
            <div key={o.id} onMouseDown={() => { onChange(String(o.id)); setOpen(false); }}
              style={{ ...item, background: String(o.id) === String(value) ? "var(--panel-2)" : "transparent" }}>
              {o.label}
            </div>
          ))}
          {!filtered.length && <div style={{ ...item, color: "var(--muted)" }}>nic nenalezeno</div>}
        </div>
      )}
    </div>
  );
}

const ACCENT = { pv_power: "green", battery_power: "blue", battery_soc: "blue", battery_soc_1: "blue", battery_soc_2: "blue", grid_power: "amber", load_power: "" };
const CHART_COLOR = { pv_power: "#3fb950", load_power: "#8b949e", battery_power: "#58a6ff", battery_soc: "#58a6ff", battery_soc_1: "#58a6ff", battery_soc_2: "#7ee787", grid_power: "#d29922", active_power: "#3fb950" };
const WIN = [
  { min: 360, label: "6 h" }, { min: 720, label: "12 h" }, { min: 1440, label: "24 h" },
  { min: 4320, label: "3 dny" }, { min: 10080, label: "7 dní" }, { min: 20160, label: "14 dní" },
  { min: 43200, label: "30 dní" },
];

function rangeLabel(minutes, offset) {
  const end = new Date(Date.now() - offset * 60000);
  const start = new Date(Date.now() - (offset + minutes) * 60000);
  const dd = (x) => x.toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" });
  const tt = (x) => x.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  return start.toDateString() === end.toDateString()
    ? `${dd(start)} ${tt(start)}–${tt(end)}`
    : `${dd(start)} ${tt(start)} – ${dd(end)} ${tt(end)}`;
}

function fmt(metric, m) {
  const v = m.value, u = m.unit;
  if (u === "W" || u === "var") {
    const k = v / 1000;
    return { value: k.toFixed(Math.abs(k) >= 10 ? 1 : 2), unit: u === "W" ? "kW" : "kvar" };
  }
  if (u === "%") return { value: Math.round(v), unit: "%" };
  if (u === "kWh") return { value: Math.round(v), unit: "kWh" };
  if (u === "Hz") return { value: v.toFixed(2), unit: "Hz" };
  if (u === "°C") return { value: v.toFixed(1), unit: "°C" };
  return { value: typeof v === "number" ? v.toFixed(1) : v, unit: u };
}

const CONTROL_ACT = {
  force_charge: { label: "Vynucené nabíjení", color: "#3fb950", icon: "⚡" },
  force_discharge: { label: "Vybíjení do sítě", color: "#d29922", icon: "🔻" },
  spiral: { label: "Spirála (vybíjení odběrem)", color: "#58a6ff", icon: "🌀" },
  set_work_mode: { label: "Změna režimu", color: "#58a6ff", icon: "⚙" },
};

function ControlBanners({ deviceIds, localityId }) {
  const [states, setStates] = useState({});
  const [outputs, setOutputs] = useState([]);
  const [plans, setPlans] = useState([]);
  const key = deviceIds.join(",");
  useEffect(() => {
    if (!deviceIds.length && !localityId) return;
    let alive = true;
    const load = () => {
      if (deviceIds.length) api.controlStates(key).then((r) => alive && setStates(r.states || {})).catch(() => {});
      api.listOutputs().then((list) => alive && setOutputs(list || [])).catch(() => {});
      api.spotPlan().then((r) => alive && setPlans(r.plans || [])).catch(() => {});
    };
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, [key, localityId]);

  const idset = new Set(deviceIds);
  const myPlans = (plans || []).filter((p) => idset.has(p.module_id) && (p.discharge?.length || p.charge?.length || p.precharge));
  const items = deviceIds.map((id) => ({ id, st: states[id] }))
    .filter(({ st }) => st && st.action && st.action !== "idle");
  const onOutputs = (outputs || []).filter((o) => o.is_on && (localityId == null || o.locality_id === localityId));
  if (!items.length && !onOutputs.length && !myPlans.length) return null;

  const fmtT = (iso) => {
    const d = new Date(iso); const now = new Date();
    const hm = d.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
    const sameDay = d.toDateString() === now.toDateString();
    const tom = new Date(now); tom.setDate(now.getDate() + 1);
    const isTom = d.toDateString() === tom.toDateString();
    return sameDay ? hm : (isTom ? `zítra ${hm}` : `${d.toLocaleDateString("cs-CZ", { day: "2-digit", month: "2-digit" })} ${hm}`);
  };

  return (
    <div style={{ margin: "0 0 12px" }}>
      {myPlans.map((p) => (
        <div key={`plan${p.module_id}`} style={{ marginBottom: 6, padding: "8px 12px", borderRadius: 10,
          border: "1px dashed var(--border)", background: "color-mix(in srgb, var(--blue) 8%, transparent)", fontSize: 12.5 }}>
          <span style={{ fontWeight: 700 }}>📅 Spotový plán</span> <span className="muted">({p.module_id})</span>
          {p.discharge?.length > 0 && (
            <div style={{ marginTop: 3 }}>🔻 Vybíjení do sítě: {p.discharge.slice(0, 3).map((w, i) =>
              <span key={i}>{i > 0 ? " · " : " "}{fmtT(w.from)}–{fmtT(w.to)} <span className="muted">(~{w.price} Kč/MWh)</span></span>)}</div>
          )}
          {p.precharge && <div style={{ marginTop: 2 }}>⚡ Předchystání ~od {fmtT(p.precharge.at)} <span className="muted">(nejlevnější {p.precharge.price} Kč/MWh)</span></div>}
          {p.charge?.length > 0 && (
            <div style={{ marginTop: 2 }}>🔋 Nabíjení (levný spot): {p.charge.slice(0, 3).map((w, i) =>
              <span key={i}>{i > 0 ? " · " : " "}{fmtT(w.from)}–{fmtT(w.to)}</span>)}</div>
          )}
        </div>
      ))}
      {items.map(({ id, st }) => {
        const act = CONTROL_ACT[st.action] || { label: st.action, color: "#58a6ff", icon: "⚡" };
        const since = st.since ? new Date(st.since) : null;
        const sinceTxt = since ? since.toLocaleString("cs-CZ", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) : "";
        const actPower = st.params?.power;
        return (
          <div key={id} className="ems-active-bar" style={{ color: act.color, background: `color-mix(in srgb, ${act.color} 14%, transparent)`, marginBottom: 6 }}>
            <span className="ems-pulse" style={{ fontSize: 16 }}>{act.icon}</span>
            <span>{act.label}{actPower != null ? ` (${(actPower / 100).toFixed(1)} kW)` : ""}</span>
            <span style={{ fontWeight: 400, fontSize: 12, opacity: 0.85, marginLeft: "auto" }}>
              {id} · od {sinceTxt}{st.source && st.source !== "manual" ? ` · ${st.source}` : ""}
            </span>
          </div>
        );
      })}
      {onOutputs.map((o) => {
        const since = o.on_since ? new Date(o.on_since) : null;
        const sinceTxt = since ? since.toLocaleString("cs-CZ", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) : "";
        const col = "#2dd4bf";
        return (
          <div key={`out${o.id}`} className="ems-active-bar" style={{ color: col, background: `color-mix(in srgb, ${col} 14%, transparent)`, marginBottom: 6 }}>
            <span className="ems-pulse" style={{ fontSize: 16 }}>🔌</span>
            <span>{o.name} · sepnuto</span>
            <span style={{ fontWeight: 400, fontSize: 12, opacity: 0.85, marginLeft: "auto" }}>
              {o.output_kind === "ewelink" ? "eWeLink" : "spotřebič"}{sinceTxt ? ` · od ${sinceTxt}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function DevicePanel({ id, locality, lastSeen, hidden = [], adapter, control = [] }) {
  const [latest, setLatest] = useState(null);
  const [hist, setHist] = useState([]);
  const [chartMetric, setChartMetric] = useState("pv_power");
  const [win, setWin] = useState(0);
  const [offset, setOffset] = useState(0);
  const err = useRef(false);
  const picked = useRef(false);
  const step = (dir) => setOffset((o) => Math.max(0, Math.min(525600, o + dir * WIN[win].min)));

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const l = await api.latest(id);
        if (!alive) return;
        setLatest(l);
        const cm = l.metrics.pv_power ? "pv_power" : (Object.keys(l.metrics)[0] || "pv_power");
        if (!picked.current) setChartMetric(cm);
        err.current = false;
      } catch (e) { err.current = true; }
    };
    tick();
    const t = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(t); };
  }, [id]);

  useEffect(() => {
    let alive = true;
    const fetchHist = async () => {
      try { const h = await api.history(id, chartMetric, WIN[win].min, offset); if (alive) setHist(h.points); }
      catch (e) { /* ignore */ }
    };
    fetchHist();
    const t = offset === 0 ? setInterval(fetchHist, 60000) : null;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [id, chartMetric, win, offset]);

  if (!latest) return (
    <section className="device"><div className="device-head"><span className="id">{id}</span></div>
      <p className="muted">Načítám…</p></section>
  );

  const metrics = latest.metrics;
  const active = latest.active ?? (Object.keys(metrics).length > 0);
  const mode = latest.states?.operation_mode;
  const auto = latest.states?.automation;
  const forcing = (mode && !["GENERAL", "SELF_USE"].includes(mode)) || !!auto;
  const present = Object.keys(metrics).filter((k) => !hidden.includes(k));
  const groups = groupMetrics(present);

  const renderCard = (k) => {
    const f = fmt(k, metrics[k]);
    return (
      <div key={k} className={`card ${ACCENT[k] ? "accent-" + ACCENT[k] : ""}`}
           onClick={() => { picked.current = true; setChartMetric(k); }}
           title="Zobrazit v grafu"
           style={{ cursor: "pointer", outline: k === chartMetric ? "1.5px solid var(--blue, #58a6ff)" : "none", outlineOffset: 1 }}>
        <div className="label" style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <Icon name={iconFor(k)} size={14} style={{ opacity: 0.65 }} />{LABELS[k] || k}
        </div>
        <div className="value">{f.value}<span className="unit">{f.unit}</span></div>
        {k.startsWith("battery_soc") && (
          <div className="soc-bar"><i style={{ width: `${Math.min(100, Math.max(0, metrics[k].value))}%` }} /></div>
        )}
      </div>
    );
  };

  return (
    <section className="device">
      <div className="device-head">
        <span className="dot" title={active ? "aktivní" : "neaktivní"}
              style={{ width: 9, height: 9, borderRadius: "50%", background: active ? "var(--green)" : "#e06c75" }} />
        <h2>{id}</h2>
        {locality && <span className="mode-chip" style={{ textTransform: "none" }}>📍 {locality}</span>}
        {mode && <span className="mode-chip">{mode}</span>}
        {!active && <span className="mode-chip" style={{ color: "#e06c75", borderColor: "#e06c75" }}>neaktivní</span>}
      </div>
      {!active && (
        <p className="muted" style={{ fontSize: 13, marginTop: -4 }}>
          Žádná čerstvá data{lastSeen ? ` — naposledy ${new Date(lastSeen).toLocaleString("cs-CZ")}` : ""}.
        </p>
      )}
      {forcing && (
        <div className="mode-banner charge">
          {(() => {
            const disch = mode === "ECO_DISCHARGE";
            const act = disch ? "vybíjení do sítě" : "nabíjení";
            return auto
              ? `🤖 ŘÍDÍ AUTOMATIZACE „${auto}" → ${act}${mode ? ` (${mode})` : ""}`
              : `⚡ NUCENÉ ${disch ? "VYBÍJENÍ DO SÍTĚ" : "NABÍJENÍ"} (ručně) — režim ${mode}`;
          })()}
        </div>
      )}
      {groups.map((g) => (
        <div key={g.id} style={{ marginBottom: 6 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 600,
                        textTransform: "uppercase", letterSpacing: 0.4, opacity: 0.55, margin: "8px 2px 4px" }}>
            <Icon name={g.icon} size={13} /> {g.label}
          </div>
          <div className="cards">
            {g.items.map(renderCard)}
          </div>
        </div>
      ))}
      {active && (
      <div className="chart-wrap">
        <div className="chart-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>{LABELS[chartMetric] || chartMetric}</span>
          <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· {rangeLabel(WIN[win].min, offset)}</span>
          <span style={{ flex: 1 }} />
          {offset > 0 && <button className="btn" style={{ padding: "2px 9px" }} onClick={() => setOffset(0)} title="zpět na teď">teď</button>}
          <button className="btn" style={{ padding: "2px 10px", fontSize: 13, lineHeight: 1 }} onClick={() => step(1)} title="o úsek zpět">◀</button>
          <button className="btn" style={{ padding: "2px 10px", fontSize: 13, lineHeight: 1 }} onClick={() => step(-1)} disabled={offset === 0} title="o úsek vpřed">▶</button>
          <button className="btn" style={{ padding: "2px 11px", fontSize: 16, lineHeight: 1, marginLeft: 6 }}
                  onClick={() => { setWin((w) => Math.max(0, w - 1)); setOffset(0); }} disabled={win === 0} title="kratší okno">−</button>
          <span className="muted" style={{ minWidth: 50, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>{WIN[win].label}</span>
          <button className="btn" style={{ padding: "2px 11px", fontSize: 16, lineHeight: 1 }}
                  onClick={() => { setWin((w) => Math.min(WIN.length - 1, w + 1)); setOffset(0); }} disabled={win === WIN.length - 1} title="delší okno (až 30 dní)">+</button>
        </div>
        {hist.length >= 2
          ? <TimeChart points={hist} unit={metrics[chartMetric]?.unit} color={CHART_COLOR[chartMetric] || "#3fb950"} />
          : <p className="muted" style={{ fontSize: 13, padding: "24px 0", textAlign: "center" }}>Pro tuto veličinu zatím není dost dat v tomto okně.</p>}
      </div>
      )}
    </section>
  );
}


// ⚡ Energetický tok lokality — animovaný diagram (FVE / síť / baterie / dům / spotřebiče)
const ACT_CZ = { charge_pv: "nabíjení z FVE", charge_grid: "nabíjení ze sítě", discharge_grid: "vybíjení do sítě",
                 discharge_load: "vybíjení do domu", idle: "self-use", export: "prodej přebytku" };
function FlowNode({ x, y, w = 150, h = 84, icon, title, value, sub, accent }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="12" fill="var(--bg)" stroke={accent || "var(--border)"} strokeWidth="1.4" />
      <text x={x + w / 2} y={y + 30} textAnchor="middle" fontSize="24">{icon}</text>
      <text x={x + w / 2} y={y + 48} textAnchor="middle" fontSize="11" fill="var(--muted)">{title}</text>
      <text x={x + w / 2} y={y + 66} textAnchor="middle" fontSize="13.5" fontWeight="700" fill={accent || "var(--fg)"}>{value}</text>
      {sub && <text x={x + w / 2} y={y + 79} textAnchor="middle" fontSize="10" fill="var(--muted)">{sub}</text>}
    </g>
  );
}
function FlowEdge({ d, kw, color, active, label, lx, ly }) {
  const wdt = Math.min(6, 1.6 + Math.abs(kw) / 2.5);
  return (
    <g>
      <path d={d} fill="none" stroke={active ? color : "var(--border)"} strokeWidth={active ? wdt : 1.2}
            strokeLinecap="round" className={active ? "eflow-anim" : ""}
            strokeDasharray={active ? "9 9" : "3 6"} opacity={active ? 0.95 : 0.45}
            markerEnd={active ? `url(#efarr-${color.replace("#", "")})` : undefined} />
      {active && <text x={lx} y={ly} textAnchor="middle" fontSize="11.5" fontWeight="700" fill={color}
                       stroke="var(--bg)" strokeWidth="3" paintOrder="stroke">{label}</text>}
    </g>
  );
}
function EnergyFlow({ locId, deviceIds, name, onClose }) {
  const [d, setD] = useState(null);
  const [pl, setPl] = useState(null);
  const [outs, setOuts] = useState([]);
  useEffect(() => {
    let alive = true;
    const load = () => {
      api.aggregateNow(deviceIds, locId).then((r) => alive && setD(r)).catch(() => {});
      api.getPlanner(locId).then((r) => alive && setPl(r)).catch(() => {});
      api.listOutputs().then((r) => alive && setOuts((r || []).filter((o) => o.locality_id == null || o.locality_id === locId))).catch(() => {});
    };
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, [locId, deviceIds.join(",")]);
  const kw = (w) => Math.abs((w || 0) / 1000);
  const f1 = (v) => `${v.toFixed(1)} kW`;
  const pvKw = d ? kw(d.pv_w) : 0;
  const batW = d?.battery_w || 0;                 // + nabíjení / − vybíjení
  const gridW = d?.grid_w || 0;                   // + import / − export
  const spiralId = pl?.config?.spiral_output_id != null ? Number(pl.config.spiral_output_id) : null;
  const spiralKw = Number(pl?.config?.spiral_power_kw) || 6;
  const cur = pl?.current;
  const outIcon = (o) => (/oh[řr]ev|spir|boiler|vod|top/i.test(o.name) ? "♨️" : "🔌");
  const COLORS = ["3fb950", "58a6ff", "a371f7", "d29922"];
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.55)", zIndex: 90,
                                    display: "flex", alignItems: "center", justifyContent: "center", padding: 12 }}>
      <div onClick={(e) => e.stopPropagation()} className="panel"
           style={{ width: "min(820px, 100%)", maxHeight: "92vh", overflow: "auto", position: "relative", padding: 14 }}>
        <style>{`.eflow-anim{animation:eflowdash 0.9s linear infinite}@keyframes eflowdash{to{stroke-dashoffset:-36}}`}</style>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <b style={{ fontSize: 15 }}>⚡ Energetický tok — {name}</b>
          <button className="btn" style={{ marginLeft: "auto", padding: "3px 10px" }} onClick={onClose}>✕</button>
        </div>
        {pl?.config?.enabled && cur && (
          <div style={{ margin: "8px 0 0", fontSize: 12.5, border: "1px dashed var(--green)", borderRadius: 999,
                        padding: "4px 12px", display: "inline-block" }}>
            🧠 Plánovač řídí: <b>{ACT_CZ[cur.action] || cur.action}</b>
            {cur.deferrable_on ? " · ♨️ spirála ON" : ""} <span className="muted">— {cur.reason}</span>
          </div>
        )}
        {!d ? <p className="muted" style={{ marginTop: 12 }}>Načítám…</p> : (
          <svg viewBox="0 0 760 470" style={{ width: "100%", marginTop: 8 }}>
            <defs>
              {COLORS.map((c) => (
                <marker key={c} id={`efarr-${c}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" fill={`#${c}`} />
                </marker>
              ))}
            </defs>
            {/* FVE → dům */}
            <FlowEdge d="M150,150 C150,200 290,205 330,222" kw={pvKw} active={pvKw > 0.05} color="#3fb950"
                      label={f1(pvKw)} lx={215} ly={192} />
            {/* síť ↔ dům */}
            {gridW >= 0
              ? <FlowEdge d="M610,150 C610,200 470,205 430,222" kw={kw(gridW)} active={kw(gridW) > 0.05} color="#58a6ff"
                          label={f1(kw(gridW))} lx={545} ly={192} />
              : <FlowEdge d="M430,222 C470,205 610,200 610,150" kw={kw(gridW)} active={kw(gridW) > 0.05} color="#3fb950"
                          label={f1(kw(gridW))} lx={545} ly={192} />}
            {/* baterie ↔ dům */}
            {batW >= 0
              ? <FlowEdge d="M335,268 C295,290 175,295 160,345" kw={kw(batW)} active={kw(batW) > 0.05} color="#a371f7"
                          label={f1(kw(batW))} lx={225} ly={305} />
              : <FlowEdge d="M160,345 C175,295 295,290 335,268" kw={kw(batW)} active={kw(batW) > 0.05} color="#a371f7"
                          label={f1(kw(batW))} lx={225} ly={305} />}
            {/* dům → spotřebiče */}
            {outs.slice(0, 3).map((o, i) => (
              <FlowEdge key={o.id} d={`M430,255 C480,${270 + i * 20} 540,${330 + i * 62} 585,${352 + i * 62}`}
                        kw={o.id === spiralId ? spiralKw : 1} active={!!o.is_on} color="#d29922"
                        label={o.id === spiralId ? f1(spiralKw) : "ON"} lx={505} ly={300 + i * 55} />
            ))}
            <FlowNode x={65} y={55} icon="☀️" title="FVE" value={f1(pvKw)}
                      sub={d.pv_forecast_days?.length ? `plán dnes ${d.pv_forecast_days[0].kwh.toFixed(0)} kWh` : null}
                      accent={pvKw > 0.05 ? "#3fb950" : null} />
            <FlowNode x={535} y={55} icon="🗼" title="Distribuce" value={gridW >= 0 ? `odběr ${f1(kw(gridW))}` : `dodávka ${f1(kw(gridW))}`}
                      accent={kw(gridW) > 0.05 ? (gridW >= 0 ? "#58a6ff" : "#3fb950") : null} />
            <FlowNode x={295} y={188} w={170} icon="🏠" title="Dům" value={f1(kw(d.load_w))}
                      sub={`dnes ${(d.cons_today_kwh ?? 0).toFixed(1)} kWh`} accent="var(--amber, #d29922)" />
            <g>
              <FlowNode x={65} y={345} icon="🔋" title="Baterie"
                        value={`${d.soc != null ? Math.round(d.soc) : "?"} %`}
                        sub={kw(batW) > 0.05 ? (batW > 0 ? `nabíjí ${f1(kw(batW))}` : `vybíjí ${f1(kw(batW))}`) : "klid"}
                        accent="#a371f7" />
              {d.soc != null && (
                <rect x={75} y={423} width={130 * Math.max(0, Math.min(100, d.soc)) / 100} height={4} rx={2} fill="#a371f7" opacity="0.9" />)}
            </g>
            {outs.slice(0, 3).map((o, i) => (
              <FlowNode key={o.id} x={585} y={330 + i * 62} w={150} h={54} icon={outIcon(o)} title={o.name}
                        value={o.is_on ? "zapnuto" : "vypnuto"} accent={o.is_on ? "#d29922" : null} />
            ))}
          </svg>
        )}
        <p className="muted" style={{ fontSize: 11, margin: "6px 0 0" }}>
          Animované čáry = aktuální tok energie (tloušťka ≈ výkon), šipka = směr. Obnovuje se každých 5 s.
        </p>
      </div>
    </div>
  );
}

function Stat({ icon, iconName, label, value, sub, color, title }) {
  return (
    <div title={title} style={{ border: "1px solid var(--border)", borderRadius: 8, background: "var(--bg)",
                                padding: "6px 10px", minWidth: 118, flex: "0 1 auto" }}>
      <div className="muted" style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
        {iconName ? <Icon name={iconName} size={13} style={{ opacity: 0.85 }} /> : <span>{icon}</span>}
        {label}
      </div>
      <div style={{ fontWeight: 700, fontSize: 14.5, color: color || "var(--fg)" }}>{value}</div>
      {sub && <div className="muted" style={{ fontSize: 11 }}>{sub}</div>}
    </div>
  );
}


// 🌀 Karta tepelného čerpadla (Stiebel ISG) — v0.64.0: stav + teploty + dnešní kWh
const HP_MODE_CZ = { heating: "topí", dhw: "ohřívá TUV", defrost: "odtává", idle: "klid" };
function HeatPumpCard({ locId }) {
  const [st, setSt] = useState(undefined);   // undefined = neptáno/loading, null = lokalita bez TČ
  const [agg, setAgg] = useState(null);      // {month_el, runtime_today_min, n_starts_today, last_start}
  useEffect(() => {
    let alive = true;
    const load = () => api.hpState(locId)
      .then((r) => alive && setSt(r.state || null))
      .catch(() => alive && setSt(null));
    const loadAgg = () => Promise.all([api.hpDaily(locId, 31), api.hpRuns(locId, 1)])
      .then(([days, runs]) => {
        if (!alive) return;
        const now = new Date();
        const monthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
        const todayKey = now.toLocaleDateString("sv-SE", { timeZone: "Europe/Prague" });
        const month_el = days.filter((d) => d.day.startsWith(monthKey)).reduce((s, d) => s + (d.el_kwh || 0), 0);
        const today = days.find((d) => d.day === todayKey);
        setAgg({ month_el, runtime_today_min: today?.runtime_min || 0, n_starts_today: today?.n_starts || 0,
                 last_start: runs[0]?.started_at || null });
      }).catch(() => {});
    load(); loadAgg();
    const t = setInterval(load, 30000);
    const t2 = setInterval(loadAgg, 120000);
    return () => { alive = false; clearInterval(t); clearInterval(t2); };
  }, [locId]);
  if (!st) return null;
  const run = !!st.compressor_on;
  const mode = HP_MODE_CZ[st.hp_mode] || st.hp_mode || "—";
  const elToday = (st.el_heating_today_kwh ?? 0) + (st.el_dhw_today_kwh ?? 0);
  const heatToday = (st.heat_heating_today_kwh ?? 0) + (st.heat_dhw_today_kwh ?? 0);
  const cop = elToday > 0 ? (heatToday / elToday) : null;
  const warn = st.fault || (st.error_code || 0) !== 0;
  const f1 = (v) => (v == null ? "—" : Number(v).toFixed(1));
  return (
    <div style={{ border: `1px solid ${warn ? "#f85149" : "var(--border)"}`, borderRadius: 8, background: "var(--bg)",
                  padding: "6px 10px", minWidth: 158, flex: "0 1 auto" }}>
      <div className="muted" style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
        <span style={run ? { display: "inline-block", animation: "hpspin 2.2s linear infinite" } : undefined}>🌀</span>
        Tepelné čerpadlo
        {warn && <span title={`porucha (kód ${st.error_code})`} style={{ color: "#f85149" }}>⚠</span>}
        {st.evu_blocked && <span title="blokace HDO/EVU">🔒</span>}
        {run && <style>{`@keyframes hpspin{to{transform:rotate(360deg)}}`}</style>}
      </div>
      <div style={{ fontWeight: 700, fontSize: 14.5, color: run ? "var(--green)" : "var(--fg)" }}>{mode}</div>
      <div className="muted" style={{ fontSize: 11, lineHeight: 1.6 }}>
        aku {f1(st.t_tank)} °C · buffer {f1(st.t_buffer)}/{f1(st.t_buffer_set)} °C · venku {f1(st.t_outdoor)} °C<br />
        dnes ⚡ {elToday.toFixed(0)} kWh · 🔥 {heatToday.toFixed(0)} kWh{cop != null ? ` · COP ${cop.toFixed(1)}` : ""}
        {agg && <><br />měsíc ⚡ {agg.month_el.toFixed(0)} kWh · dnes běh {Math.floor(agg.runtime_today_min / 60)}h{String(Math.round(agg.runtime_today_min % 60)).padStart(2, "0")}m · {agg.n_starts_today}× start
        {agg.last_start ? ` · poslední ${new Date(agg.last_start).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}` : ""}</>}
      </div>
    </div>
  );
}

function LocalityNow({ deviceIds, localityId }) {
  const [d, setD] = useState(null);
  const [ts, setTs] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.aggregateNow(deviceIds, localityId)
      .then((r) => { if (alive) { setD(r); setTs(new Date()); } }).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, [deviceIds.join(","), localityId]);
  if (!d) return null;
  const kw = (d.pv_w / 1000);
  const loadKw = (d.load_w ?? 0) / 1000;
  const gridW = d.grid_w ?? 0;                 // + import / − export (W)
  const impKw = gridW > 0 ? gridW / 1000 : 0;
  const expKw = gridW < 0 ? -gridW / 1000 : 0;
  const fmt = (v, dec = 1) => v.toFixed(dec);
  const czk = (v) => `${v >= 100 ? v.toFixed(0) : v.toFixed(2)} Kč`;
  const fdays = d.pv_forecast_days || [];
  const fLabel = ["dnes", "zítra", "pozítří"];
  const planMain = fdays.length ? `${fmt(fdays[0].kwh, 0)} kWh` : null;
  const planSub = fdays.slice(1).map((x, i) => `${fLabel[i + 1]} ${fmt(x.kwh, 0)}`).join(" · ");
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "stretch", margin: "8px 0 0", fontWeight: 400 }}>
      <Stat icon="🏠" label="Spotřeba" color="var(--amber, #d29922)"
            value={`${fmt(loadKw)} kW`} sub={`dnes ${fmt(d.cons_today_kwh ?? 0)} kWh`}
            title="Okamžitý příkon domu · pod tím součet za dnešní den" />
      <Stat icon="☀️" label="FVE" color="var(--green)"
            value={`${fmt(kw)} kW`} sub={`dnes ${fmt(d.today_kwh)} kWh`}
            title="Okamžitý výkon FVE · pod tím dnešní výroba" />
      {planMain && (
        <Stat icon="🔮" label="Plán FVE dnes" color="var(--green)"
              value={planMain} sub={planSub || null}
              title="Predikovaná výroba (ranní snapshot); zítřek/pozítří dle předpovědi" />)}
      {d.soc != null && (
        <Stat iconName="battery" label="Baterie" color="var(--blue)" value={`${Math.round(d.soc)} %`}
              title="Aktuální nabití baterie" />)}
      {d.import_kwh != null && (
        <Stat iconName="tower" label="Ze sítě" color="var(--blue)"
              value={`${fmt(impKw)} kW`}
              sub={`dnes ${fmt(d.import_kwh)} kWh${d.import_czk != null ? ` · ${czk(d.import_czk)}` : ""}`}
              title="Okamžitý odběr z distribuce · dnešní součet a cena dle sazebníku" />)}
      {d.export_kwh != null && (
        <Stat icon="↗️" label="Do sítě" color="var(--green)"
              value={`${fmt(expKw)} kW`}
              sub={`dnes ${fmt(d.export_kwh)} kWh${d.export_czk != null ? ` · ${czk(d.export_czk)}` : ""}`}
              title="Okamžitý přetok do distribuce · dnešní součet a výnos dle sazebníku" />)}
      {localityId && <HeatPumpCard locId={localityId} />}
      {ts && (
        <div className="muted" style={{ fontSize: 10.5, alignSelf: "flex-end", marginLeft: "auto", textAlign: "right", lineHeight: 1.5 }}
             title="Velké číslo (kW) je okamžitá hodnota, řádek pod ním jsou součty za dnešní den.">
          kW = teď · kWh/Kč = dnes {ts.toLocaleDateString("cs-CZ")}<br />aktualizováno {ts.toLocaleTimeString("cs-CZ")}
        </div>
      )}
    </div>
  );
}

function LocalitySection({ name, devs, open, onToggle }) {
  const ids = devs.map((d) => d.device_id);
  const locId = devs[0].locality_id;
  const [flow, setFlow] = useState(false);
  return (
    <section style={{ marginBottom: open ? 26 : 10 }}>
      <h2 style={{ margin: "0 0 4px", fontSize: 18, cursor: "pointer", userSelect: "none" }}
          onClick={onToggle} title={open ? "Sbalit lokalitu" : "Rozbalit lokalitu"}>
        <span style={{ fontSize: 13, marginRight: 6, opacity: 0.7 }}>{open ? "▾" : "▸"}</span>
        {name === "—" ? "Bez lokality" : `📍 ${name}`}
        {locId && (
          <button className="btn" title="Energetický tok lokality (živý diagram)"
                  onClick={(e) => { e.stopPropagation(); setFlow(true); }}
                  style={{ marginLeft: 10, padding: "2px 10px", fontSize: 13, verticalAlign: "2px" }}>⚡ tok</button>)}
      </h2>
      {flow && locId && <EnergyFlow locId={locId} deviceIds={ids} name={name} onClose={() => setFlow(false)} />}
      <LocalityNow deviceIds={ids} localityId={locId} />
      {open && (<>
        <ControlBanners deviceIds={ids} localityId={locId} />
        <LocalityChart deviceIds={ids} />
        {locId && (
          <div className="card" style={{ marginTop: 14 }}>
            <h3 style={{ margin: "0 0 6px", fontSize: 15 }}>Predikce 24–48 h</h3>
            <ForecastChart localityId={locId} />
          </div>
        )}
        {locId && <TempChart localityId={locId} deviceIds={ids} />}
        {devs.map((d) => <DevicePanel key={d.device_id} id={d.device_id} locality={d.locality} lastSeen={d.last_seen} hidden={d.hidden_metrics || []} adapter={d.adapter} control={d.control_enabled || []} />)}
        {locId && <BillingTable localityId={locId} />}
      </>)}
    </section>
  );
}

function LocalityChart({ deviceIds }) {
  const [win, setWin] = useState(2); // default 24 h
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const step = (dir) => setOffset((o) => Math.max(0, Math.min(525600, o + dir * WIN[win].min)));

  useEffect(() => {
    let alive = true;
    const load = () => api.aggregate(deviceIds, ["pv_power", "load", "grid_power", "battery_power", "battery_soc"], WIN[win].min, offset)
      .then((r) => alive && setData(r.metrics)).catch(() => {});
    load();
    const t = offset === 0 ? setInterval(load, 60000) : null;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [deviceIds.join(","), win, offset]);

  const series = data ? [
    { label: "Výroba FVE", color: "#3fb950", points: data.pv_power || [] },
    { label: "Spotřeba lokality", color: "#d29922", points: data.load || [] },
    { label: "Síť (export +/odběr −)", color: "#58a6ff", points: data.grid_power || [] },
    { label: "Baterie (+ nabíjení)", color: "#a371f7", points: data.battery_power || [] },
    { label: "SoC baterie", color: "#a371f7", axis: "pct", points: data.battery_soc || [] },
  ].filter((x) => x.points.length >= 2) : [];

  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>Souhrn lokality</h3>
        <span className="muted" style={{ fontSize: 12 }}>· {rangeLabel(WIN[win].min, offset)}</span>
        <span style={{ flex: 1 }} />
        {offset > 0 && <button className="btn" style={{ padding: "2px 9px" }} onClick={() => setOffset(0)} title="zpět na teď">teď</button>}
        <button className="btn" style={{ padding: "2px 10px", fontSize: 13, lineHeight: 1 }} onClick={() => step(1)} title="o úsek zpět">◀</button>
        <button className="btn" style={{ padding: "2px 10px", fontSize: 13, lineHeight: 1 }} onClick={() => step(-1)} disabled={offset === 0} title="o úsek vpřed">▶</button>
        <button className="btn" style={{ padding: "2px 11px", fontSize: 16, lineHeight: 1, marginLeft: 6 }}
                onClick={() => { setWin((w) => Math.max(0, w - 1)); setOffset(0); }} disabled={win === 0}>−</button>
        <span className="muted" style={{ minWidth: 50, textAlign: "center" }}>{WIN[win].label}</span>
        <button className="btn" style={{ padding: "2px 11px", fontSize: 16, lineHeight: 1 }}
                onClick={() => { setWin((w) => Math.min(WIN.length - 1, w + 1)); setOffset(0); }} disabled={win === WIN.length - 1}>+</button>
      </div>
      {!data ? <p className="muted" style={{ fontSize: 12 }}>Načítám…</p>
             : <MultiChart series={series} />}
    </div>
  );
}

export default function Dashboard() {
  const [devices, setDevices] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(() => localStorage.getItem("ems.dash.locality") || "");
  const [openMap, setOpenMap] = useState(() => {
    try { return JSON.parse(localStorage.getItem("ems.dash.open") || "{}"); } catch { return {}; }
  });

  useEffect(() => {
    api.devices().then(setDevices).catch((e) => setError(e.message));
  }, []);

  if (error) return <main><p className="muted">Chyba: {error}</p></main>;
  if (!devices) return <main><p className="muted">Načítám zařízení…</p></main>;
  if (!devices.length) return <main><p className="muted">Zatím žádná data. Běží kolektor?</p></main>;

  const groups = {};
  devices.forEach((d) => { const k = d.locality || "—"; (groups[k] = groups[k] || []).push(d); });
  const names = Object.keys(groups).sort((a, b) =>
    a === "—" ? 1 : b === "—" ? -1 : a.localeCompare(b, "cs"));

  // vybraná lokalita: uložená poslední (pokud pořád existuje), jinak první — default rozbalená
  const current = names.includes(selected) ? selected : names[0];
  const isOpen = (n) => (n in openMap ? openMap[n] : (names.length === 1 || n === current));
  const toggle = (n) => setOpenMap((m) => {
    const x = { ...m, [n]: !(n in m ? m[n] : (names.length === 1 || n === current)) };
    localStorage.setItem("ems.dash.open", JSON.stringify(x));
    return x;
  });

  return (
    <main>
      {names.length > 1 && (
        <p className="muted" style={{ fontSize: 12, margin: "0 0 10px" }}>
          {names.length} lokalit — klikem na název lokalitu sbalíš / rozbalíš.
        </p>
      )}
      {names.map((n) => (
        <LocalitySection key={n} name={n} devs={groups[n]} open={isOpen(n)} onToggle={() => toggle(n)} />
      ))}
    </main>
  );
}
