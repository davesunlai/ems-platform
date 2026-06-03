import { useEffect, useState, useRef } from "react";
import { api } from "../api";
import TimeChart from "../components/TimeChart";

const LABELS = {
  pv_power: "FVE výkon", load_power: "Spotřeba", battery_power: "Baterie",
  battery_soc: "Baterie SoC", grid_power: "Síť", active_power: "Činný výkon",
  reactive_power: "Jalový výkon", frequency: "Frekvence", temperature: "Teplota",
  energy_pv_total: "FVE celkem", energy_import: "Import celkem", energy_export: "Export celkem",
  voltage: "Napětí", current: "Proud",
};
const ACCENT = { pv_power: "green", battery_power: "blue", battery_soc: "blue", grid_power: "amber", load_power: "" };
const ORDER = ["pv_power","load_power","battery_power","battery_soc","grid_power","active_power",
               "frequency","temperature","energy_pv_total","energy_import","energy_export"];
const WIN = [
  { min: 360, label: "6 h" }, { min: 720, label: "12 h" }, { min: 1440, label: "24 h" },
  { min: 4320, label: "3 dny" }, { min: 10080, label: "7 dní" }, { min: 20160, label: "14 dní" },
  { min: 43200, label: "30 dní" },
];

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

function DevicePanel({ id }) {
  const [latest, setLatest] = useState(null);
  const [hist, setHist] = useState([]);
  const [chartMetric, setChartMetric] = useState("pv_power");
  const [win, setWin] = useState(0);
  const err = useRef(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const l = await api.latest(id);
        if (!alive) return;
        setLatest(l);
        const cm = l.metrics.pv_power ? "pv_power" : Object.keys(l.metrics)[0];
        setChartMetric(cm);
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
      try { const h = await api.history(id, chartMetric, WIN[win].min); if (alive) setHist(h.points); }
      catch (e) { /* ignore */ }
    };
    fetchHist();
    const t = setInterval(fetchHist, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [id, chartMetric, win]);

  if (!latest) return (
    <section className="device"><div className="device-head"><span className="id">{id}</span></div>
      <p className="muted">Načítám…</p></section>
  );

  const metrics = latest.metrics;
  const mode = latest.states?.operation_mode;
  const auto = latest.states?.automation;
  const forcing = (mode && !["GENERAL", "SELF_USE"].includes(mode)) || !!auto;
  const keys = ORDER.filter((k) => k in metrics).concat(Object.keys(metrics).filter((k) => !ORDER.includes(k)));

  return (
    <section className="device">
      <div className="device-head">
        <span className="dot" style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--green)" }} />
        <h2>{id}</h2>
        {mode && <span className="mode-chip">{mode}</span>}
      </div>
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
            <div key={k} className={`card ${ACCENT[k] ? "accent-" + ACCENT[k] : ""}`}>
              <div className="label">{LABELS[k] || k}</div>
              <div className="value">{f.value}<span className="unit">{f.unit}</span></div>
              {k === "battery_soc" && (
                <div className="soc-bar"><i style={{ width: `${Math.min(100, Math.max(0, metrics[k].value))}%` }} /></div>
              )}
            </div>
          );
        })}
      </div>
      <div className="chart-wrap">
        <div className="chart-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>{LABELS[chartMetric] || chartMetric}</span>
          <span style={{ flex: 1 }} />
          <button className="btn" style={{ padding: "2px 11px", fontSize: 16, lineHeight: 1 }}
                  onClick={() => setWin((w) => Math.max(0, w - 1))} disabled={win === 0} title="kratší okno">−</button>
          <span className="muted" style={{ minWidth: 50, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>{WIN[win].label}</span>
          <button className="btn" style={{ padding: "2px 11px", fontSize: 16, lineHeight: 1 }}
                  onClick={() => setWin((w) => Math.min(WIN.length - 1, w + 1))} disabled={win === WIN.length - 1} title="delší okno (až 30 dní)">+</button>
        </div>
        <TimeChart points={hist} unit={metrics[chartMetric]?.unit} color="#3fb950" />
      </div>
    </section>
  );
}

export default function Dashboard() {
  const [devices, setDevices] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.devices().then(setDevices).catch((e) => setError(e.message));
  }, []);

  if (error) return <main><p className="muted">Chyba: {error}</p></main>;
  if (!devices) return <main><p className="muted">Načítám zařízení…</p></main>;
  if (!devices.length) return <main><p className="muted">Zatím žádná data. Běží kolektor?</p></main>;

  return <main>{devices.map((d) => <DevicePanel key={d.device_id} id={d.device_id} />)}</main>;
}
