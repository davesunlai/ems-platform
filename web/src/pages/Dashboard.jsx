import { useEffect, useState, useRef } from "react";
import { api } from "../api";
import Sparkline from "../components/Sparkline";

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
        const h = await api.history(id, cm, 360);
        if (alive) setHist(h.points);
        err.current = false;
      } catch (e) { err.current = true; }
    };
    tick();
    const t = setInterval(tick, 5000);
    return () => { alive = false; clearInterval(t); };
  }, [id]);

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
        <div className="chart-title">{LABELS[chartMetric] || chartMetric} — posledních 6 h</div>
        <Sparkline points={hist} color="#3fb950" />
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
