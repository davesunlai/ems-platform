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

function LocalityNow({ deviceIds, localityId }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.aggregateNow(deviceIds, localityId).then((r) => alive && setD(r)).catch(() => {});
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
  const fmt = (v, dec = 1) => (Math.abs(v) >= 10 ? v.toFixed(dec) : v.toFixed(dec));
  const czk = (v) => `${v >= 100 ? v.toFixed(0) : v.toFixed(2)} Kč`;
  return (
    <span style={{ fontWeight: 400, color: "var(--muted)", marginLeft: 10 }}>
      · spotřeba <strong style={{ color: "var(--amber, #d29922)" }}>{fmt(loadKw)} kW / {fmt(d.cons_today_kwh ?? 0)} kWh</strong>
      {" · FVE "}<strong style={{ color: "var(--green)" }}>{fmt(kw)} kW / {fmt(d.today_kwh)} kWh</strong>
      {d.soc != null && <> · <Icon name="battery" size={14} style={{ verticalAlign: "-2px", opacity: 0.85 }} /> <strong style={{ color: "var(--blue)" }}>{Math.round(d.soc)} %</strong></>}
      {d.import_kwh != null && <> {" · "}<Icon name="tower" size={14} style={{ verticalAlign: "-2px", opacity: 0.85 }} /> ze sítě <strong style={{ color: "var(--blue)" }}>{fmt(impKw)} kW / {fmt(d.import_kwh)} kWh{d.import_czk != null ? ` / ${czk(d.import_czk)}` : ""}</strong></>}
      {d.export_kwh != null && <> · do sítě <strong style={{ color: "var(--green)" }}>{fmt(expKw)} kW / {fmt(d.export_kwh)} kWh{d.export_czk != null ? ` / ${czk(d.export_czk)}` : ""}</strong></>}
    </span>
  );
}

function LocalityChart({ deviceIds }) {
  const [win, setWin] = useState(2); // default 24 h
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const step = (dir) => setOffset((o) => Math.max(0, Math.min(525600, o + dir * WIN[win].min)));

  useEffect(() => {
    let alive = true;
    const load = () => api.aggregate(deviceIds, ["pv_power", "load", "grid_power", "battery_power"], WIN[win].min, offset)
      .then((r) => alive && setData(r.metrics)).catch(() => {});
    load();
    const t = offset === 0 ? setInterval(load, 60000) : null;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [deviceIds.join(","), win, offset]);

  const series = data ? [
    { label: "Výroba FVE", color: "#3fb950", points: data.pv_power || [] },
    { label: "Spotřeba lokality", color: "#d29922", points: data.load || [] },
    { label: "Síť (export +/odběr −)", color: "#58a6ff", points: data.grid_power || [] },
    { label: "Baterie", color: "#a371f7", points: data.battery_power || [] },
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

  // vybraná lokalita: uložená poslední (pokud pořád existuje), jinak první
  const current = names.includes(selected) ? selected : names[0];
  const pick = (name) => { if (name) { setSelected(name); localStorage.setItem("ems.dash.locality", name); } };

  const devs = groups[current];
  const ids = devs.map((d) => d.device_id);
  const locOptions = names.map((n) => ({ id: n, label: n === "—" ? "Bez lokality" : n }));

  return (
    <main>
      {names.length > 1 && (
        <div className="panel" style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <strong style={{ fontSize: 14 }}>Lokalita</strong>
          <div style={{ minWidth: 240, flex: "0 1 360px" }}>
            <SearchSelect value={current} options={locOptions} allowEmpty={false}
              placeholder="Hledat lokalitu…" onChange={pick} />
          </div>
          <span className="muted" style={{ fontSize: 12 }}>{names.length} lokalit k dispozici</span>
        </div>
      )}
      <section style={{ marginBottom: 26 }}>
        <h2 style={{ margin: "0 0 12px", fontSize: 18 }}>
          {current === "—" ? "Bez lokality" : `📍 ${current}`}
          <LocalityNow deviceIds={ids} localityId={devs[0].locality_id} />
        </h2>
        <ControlBanners deviceIds={ids} localityId={devs[0].locality_id} />
        <LocalityChart deviceIds={ids} />
        {devs[0].locality_id && (
          <div className="card" style={{ marginTop: 14 }}>
            <h3 style={{ margin: "0 0 6px", fontSize: 15 }}>Predikce 24–48 h</h3>
            <ForecastChart localityId={devs[0].locality_id} />
          </div>
        )}
        {devs[0].locality_id && <TempChart localityId={devs[0].locality_id} deviceIds={ids} />}
        {devs.map((d) => <DevicePanel key={d.device_id} id={d.device_id} locality={d.locality} lastSeen={d.last_seen} hidden={d.hidden_metrics || []} adapter={d.adapter} control={d.control_enabled || []} />)}
        {devs[0].locality_id && <BillingTable localityId={devs[0].locality_id} />}
      </section>
    </main>
  );
}
