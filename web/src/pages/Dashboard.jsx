import { useEffect, useState, useRef } from "react";
import { api } from "../api";
import TimeChart from "../components/TimeChart";
import MultiChart from "../components/MultiChart";

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

const LABELS = {
  pv_power: "FVE výkon", load_power: "Spotřeba", battery_power: "Baterie",
  battery_soc: "Baterie SoC", grid_power: "Síť", active_power: "Činný výkon",
  reactive_power: "Jalový výkon", frequency: "Frekvence", temperature: "Teplota",
  energy_pv_total: "FVE celkem", energy_import: "Import celkem", energy_export: "Export celkem",
  voltage: "Napětí", current: "Proud",
};
const ACCENT = { pv_power: "green", battery_power: "blue", battery_soc: "blue", grid_power: "amber", load_power: "" };
const CHART_COLOR = { pv_power: "#3fb950", load_power: "#8b949e", battery_power: "#58a6ff", battery_soc: "#58a6ff", grid_power: "#d29922", active_power: "#3fb950" };
const ORDER = ["pv_power","load_power","battery_power","battery_soc","grid_power","active_power",
               "frequency","temperature","energy_pv_total","energy_import","energy_export"];
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

function DevicePanel({ id, locality, lastSeen }) {
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
  const keys = ORDER.filter((k) => k in metrics).concat(Object.keys(metrics).filter((k) => !ORDER.includes(k)));

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
      <div className="cards">
        {keys.map((k) => {
          const f = fmt(k, metrics[k]);
          return (
            <div key={k} className={`card ${ACCENT[k] ? "accent-" + ACCENT[k] : ""}`}
                 onClick={() => { picked.current = true; setChartMetric(k); }}
                 title="Zobrazit v grafu"
                 style={{ cursor: "pointer", outline: k === chartMetric ? "1.5px solid var(--blue, #58a6ff)" : "none", outlineOffset: 1 }}>
              <div className="label">{LABELS[k] || k}</div>
              <div className="value">{f.value}<span className="unit">{f.unit}</span></div>
              {k === "battery_soc" && (
                <div className="soc-bar"><i style={{ width: `${Math.min(100, Math.max(0, metrics[k].value))}%` }} /></div>
              )}
            </div>
          );
        })}
      </div>
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

function LocalityNow({ deviceIds }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.aggregateNow(deviceIds).then((r) => alive && setD(r)).catch(() => {});
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, [deviceIds.join(",")]);
  if (!d) return null;
  const kw = (d.pv_w / 1000);
  const fmt = (v, dec = 1) => (Math.abs(v) >= 10 ? v.toFixed(dec) : v.toFixed(dec));
  return (
    <span style={{ fontWeight: 400, color: "var(--muted)", marginLeft: 10 }}>
      · součet <strong style={{ color: "var(--green)" }}>{fmt(kw)} kW</strong>
      {d.soc != null && <> · baterie <strong style={{ color: "var(--blue)" }}>{Math.round(d.soc)} %</strong></>}
      {" · dnes Σ "}<strong style={{ color: "var(--fg)" }}>{fmt(d.today_kwh)} kWh</strong>
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
    const load = () => api.aggregate(deviceIds, ["pv_power", "load_power", "grid_power", "battery_power"], WIN[win].min, offset)
      .then((r) => alive && setData(r.metrics)).catch(() => {});
    load();
    const t = offset === 0 ? setInterval(load, 60000) : null;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [deviceIds.join(","), win, offset]);

  const series = data ? [
    { label: "Výroba FVE", color: "#3fb950", points: data.pv_power || [] },
    { label: "Spotřeba lokality", color: "#d29922", points: data.load_power || [] },
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

function fmtKWh(v) {
  return v >= 1000 ? `${(v / 1000).toFixed(2)} MWh` : `${v.toFixed(0)} kWh`;
}

function BillingTable({ localityId }) {
  const [b, setB] = useState(null);
  useEffect(() => {
    let alive = true;
    api.localityBilling(localityId).then((r) => alive && setB(r)).catch(() => {});
    return () => { alive = false; };
  }, [localityId]);

  if (!b || !b.configured) return null;
  const lim = b.settings.export_limit_kwh;
  const exp = b.totals.export_kwh;
  const pct = lim ? Math.min(100, (exp / lim) * 100) : 0;
  const over = lim && exp >= lim;
  const fmtMonth = (m) => {
    const [y, mo] = m.split("-");
    return new Date(y, mo - 1, 1).toLocaleDateString("cs-CZ", { month: "long", year: "numeric" });
  };

  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>Zúčtovací období</h3>
        <span className="muted" style={{ fontSize: 13 }}>
          {new Date(b.period.start).toLocaleDateString("cs-CZ")} – {new Date(b.period.end).toLocaleDateString("cs-CZ")}
        </span>
      </div>

      {lim != null && (
        <div style={{ margin: "10px 0 4px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
            <span>Přetoky za období: <strong style={{ color: over ? "#e06c75" : "var(--green)" }}>{fmtKWh(exp)}</strong></span>
            <span className="muted">limit {fmtKWh(lim)}</span>
          </div>
          <div style={{ height: 8, background: "var(--border)", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: over ? "#e06c75" : pct > 80 ? "#d29922" : "var(--green)" }} />
          </div>
        </div>
      )}

      <table style={{ marginTop: 12, width: "100%" }}>
        <thead><tr>
          <th style={{ textAlign: "left" }}>Měsíc</th>
          <th style={{ textAlign: "right" }}>Výroba</th>
          <th style={{ textAlign: "right" }}>Spotřeba</th>
          <th style={{ textAlign: "right" }}>Přetoky</th>
          <th style={{ textAlign: "right" }}>Nákup od distributora</th>
        </tr></thead>
        <tbody>
          {b.baseline && (b.baseline.export_kwh || b.baseline.import_kwh) ? (
            <tr className="muted">
              <td>Před spuštěním měření</td>
              <td style={{ textAlign: "right" }}>—</td>
              <td style={{ textAlign: "right" }}>—</td>
              <td style={{ textAlign: "right" }}>{b.baseline.export_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{b.baseline.import_kwh.toFixed(0)} kWh</td>
            </tr>
          ) : null}
          {b.months.map((r) => (
            <tr key={r.month}>
              <td>{fmtMonth(r.month)}</td>
              <td style={{ textAlign: "right" }}>{r.prod_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{r.cons_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right", color: "var(--green)" }}>{r.export_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{r.import_kwh.toFixed(0)} kWh</td>
            </tr>
          ))}
          {!b.months.length && <tr><td colSpan="5" className="muted">Zatím žádná data v tomto období.</td></tr>}
        </tbody>
        {b.months.length > 0 && (
          <tfoot><tr style={{ fontWeight: 600, borderTop: "1px solid var(--border)" }}>
            <td>Celkem za období</td>
            <td style={{ textAlign: "right" }}>{fmtKWh(b.totals.prod_kwh)}</td>
            <td style={{ textAlign: "right" }}>{fmtKWh(b.totals.cons_kwh)}</td>
            <td style={{ textAlign: "right", color: "var(--green)" }}>{fmtKWh(b.totals.export_kwh)}</td>
            <td style={{ textAlign: "right" }}>{fmtKWh(b.totals.import_kwh)}</td>
          </tr></tfoot>
        )}
      </table>
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
          <LocalityNow deviceIds={ids} />
        </h2>
        <LocalityChart deviceIds={ids} />
        {devs[0].locality_id && <BillingTable localityId={devs[0].locality_id} />}
        {devs.map((d) => <DevicePanel key={d.device_id} id={d.device_id} locality={d.locality} lastSeen={d.last_seen} />)}
      </section>
    </main>
  );
}
