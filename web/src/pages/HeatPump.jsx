// 🌀 Stránka Tepelné čerpadlo: graf teplot s podbarvením běhů, denní sloupce el+COP, historie spínání.
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";

const MODE_CZ = { heating: "topení", dhw: "TUV", defrost: "odtávání", cooling: "chlazení", nhz: "dohřev" };
const MODE_COLOR = { heating: "#3fb950", dhw: "#58a6ff", defrost: "#d29922", cooling: "#39c5cf", nhz: "#f85149" };
const RANGES = { "24h": 24, "48h": 48, "7 dní": 168, "31 dní": 744 };

function TempChart({ rows, runs }) {
  const W = 760, H = 300, padL = 40, padR = 40, padT = 10, padB = 22;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const [hov, setHov] = useState(null);
  if (!rows.length) return <p className="muted">Zatím žádná data (telemetrie se sbírá po 30 s).</p>;
  const t0 = new Date(rows[0].ts).getTime(), t1 = new Date(rows[rows.length - 1].ts).getTime() || t0 + 1;
  const X = (t) => padL + plotW * (t - t0) / Math.max(1, t1 - t0);
  const temps = rows.flatMap((r) => [r.t_tank, r.t_buffer, r.t_buffer_set].filter((v) => v != null));
  const lo = Math.floor(Math.min(...temps, 20) - 2), hi = Math.ceil(Math.max(...temps, 60) + 2);
  const Y = (v) => padT + plotH * (1 - (v - lo) / Math.max(1, hi - lo));
  const outs = rows.map((r) => r.t_outdoor).filter((v) => v != null);
  const olo = Math.floor(Math.min(...outs, 0) - 2), ohi = Math.ceil(Math.max(...outs, 25) + 2);
  const Yo = (v) => padT + plotH * (1 - (v - olo) / Math.max(1, ohi - olo));
  const path = (key, yfn) => rows.filter((r) => r[key] != null)
    .map((r, i) => `${i ? "L" : "M"}${X(new Date(r.ts).getTime()).toFixed(1)},${yfn(r[key]).toFixed(1)}`).join(" ");
  const fmtT = (iso) => new Date(iso).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  const nearest = hov != null ? rows.reduce((b, r) => Math.abs(new Date(r.ts) - hov) < Math.abs(new Date(b.ts) - hov) ? r : b, rows[0]) : null;
  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%" }}
           onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect();
             const fx = (e.clientX - r.left) / r.width * W;
             setHov(fx >= padL && fx <= W - padR ? t0 + (fx - padL) / plotW * (t1 - t0) : null); }}
           onMouseLeave={() => setHov(null)}>
        {/* podbarvení běhů */}
        {runs.map((run) => {
          const a = new Date(run.started_at).getTime();
          const b = run.ended_at ? new Date(run.ended_at).getTime() : t1;
          if (b < t0 || a > t1) return null;
          const x1 = X(Math.max(a, t0)), x2 = X(Math.min(b, t1));
          return <rect key={run.id} x={x1} y={padT} width={Math.max(1.5, x2 - x1)} height={plotH}
                       fill={MODE_COLOR[run.mode] || "#3fb950"} opacity="0.14" />;
        })}
        {[...Array(5)].map((_, i) => { const v = lo + (hi - lo) * i / 4; return (
          <g key={i}><line x1={padL} x2={W - padR} y1={Y(v)} y2={Y(v)} stroke="var(--border)" strokeDasharray="2 4" />
            <text x={padL - 5} y={Y(v) + 3} textAnchor="end" fontSize="9.5" fill="var(--muted)">{v.toFixed(0)}</text></g>); })}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => { const v = olo + (ohi - olo) * f; return (
          <text key={f} x={W - padR + 5} y={Yo(v) + 3} textAnchor="start" fontSize="9.5" fill="#8b949e">{v.toFixed(0)}</text>); })}
        <text x={12} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="var(--muted)"
              transform={`rotate(-90 12 ${padT + plotH / 2})`}>°C</text>
        <text x={W - 8} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="#8b949e"
              transform={`rotate(90 ${W - 8} ${padT + plotH / 2})`}>venku °C</text>
        <path d={path("t_tank", Y)} fill="none" stroke="#e3b341" strokeWidth="1.8" />
        <path d={path("t_buffer", Y)} fill="none" stroke="#3fb950" strokeWidth="1.8" />
        <path d={path("t_buffer_set", Y)} fill="none" stroke="#3fb950" strokeWidth="1.3" strokeDasharray="5 4" opacity="0.7" />
        <path d={path("t_outdoor", Yo)} fill="none" stroke="#8b949e" strokeWidth="1.5" strokeDasharray="2 3" />
        {rows.length > 1 && [0, 0.25, 0.5, 0.75, 1].map((f) => { const t = t0 + (t1 - t0) * f; return (
          <text key={f} x={X(t)} y={H - 6} textAnchor="middle" fontSize="9.5" fill="var(--muted)">{fmtT(new Date(t).toISOString())}</text>); })}
        {nearest && <line x1={X(new Date(nearest.ts).getTime())} x2={X(new Date(nearest.ts).getTime())}
                          y1={padT} y2={padT + plotH} stroke="var(--muted)" strokeWidth="0.7" />}
      </svg>
      {nearest && (
        <div style={{ position: "absolute", top: 6, right: 46, background: "var(--panel)", border: "1px solid var(--border)",
                      borderRadius: 8, padding: "5px 9px", fontSize: 11.5, pointerEvents: "none" }}>
          <b>{fmtT(nearest.ts)}</b>
          <div>🟡 aku {nearest.t_tank ?? "—"} °C · 🟢 buffer {nearest.t_buffer ?? "—"}/{nearest.t_buffer_set ?? "—"} °C</div>
          <div>venku {nearest.t_outdoor ?? "—"} °C · kompresor {nearest.comp ? "běží" : "stojí"}</div>
        </div>
      )}
      <div className="muted" style={{ fontSize: 11.5, display: "flex", gap: 14, flexWrap: "wrap", marginTop: 4 }}>
        <span>🟡 aku (508)</span><span>🟢 buffer (517, ┄ set)</span><span style={{ color: "#8b949e" }}>┄ venku (pravá osa)</span>
        {Object.entries(MODE_CZ).slice(0, 3).map(([k, l]) => (
          <span key={k}><span style={{ display: "inline-block", width: 10, height: 10, background: MODE_COLOR[k], opacity: 0.35, borderRadius: 2, marginRight: 4 }} />běh: {l}</span>))}
      </div>
    </div>
  );
}

function DailyBars({ days }) {
  const W = 760, H = 190, padL = 40, padR = 40, padT = 10, padB = 30;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  if (!days.length) return null;
  const maxEl = Math.max(1, ...days.map((d) => d.el_kwh || 0));
  const cops = days.filter((d) => d.cop != null);
  const maxCop = Math.max(5, ...cops.map((d) => d.cop));
  const bw = Math.min(34, plotW / days.length * 0.7);
  const Xc = (i) => padL + plotW * (i + 0.5) / days.length;
  const Yel = (v) => padT + plotH * (1 - v / maxEl);
  const Ycop = (v) => padT + plotH * (1 - v / maxCop);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%" }}>
      {[0.5, 1].map((f) => (
        <g key={f}><line x1={padL} x2={W - padR} y1={Yel(maxEl * f)} y2={Yel(maxEl * f)} stroke="var(--border)" strokeDasharray="2 4" />
          <text x={padL - 5} y={Yel(maxEl * f) + 3} textAnchor="end" fontSize="9.5" fill="var(--muted)">{(maxEl * f).toFixed(0)}</text></g>))}
      <text x={12} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="var(--muted)" transform={`rotate(-90 12 ${padT + plotH / 2})`}>kWh el.</text>
      <text x={W - 8} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="#a371f7" transform={`rotate(90 ${W - 8} ${padT + plotH / 2})`}>COP</text>
      {days.map((d, i) => {
        const hH = plotH * (d.el_heating_kwh || 0) / maxEl, dH = plotH * (d.el_dhw_kwh || 0) / maxEl;
        return (
          <g key={d.day}>
            <rect x={Xc(i) - bw / 2} y={padT + plotH - hH} width={bw} height={hH} fill="#3fb950" opacity="0.85">
              <title>{d.day}: topení {d.el_heating_kwh} kWh</title></rect>
            {dH > 0 && <rect x={Xc(i) - bw / 2} y={padT + plotH - hH - dH} width={bw} height={dH} fill="#58a6ff" opacity="0.85">
              <title>{d.day}: TUV {d.el_dhw_kwh} kWh</title></rect>}
            {d.cop != null && <circle cx={Xc(i)} cy={Ycop(d.cop)} r="3.2" fill="#a371f7"><title>COP {d.cop}</title></circle>}
            <text x={Xc(i)} y={H - 16} textAnchor="middle" fontSize="9" fill="var(--muted)">{d.day.slice(8)}.{d.day.slice(5, 7)}.</text>
            <text x={Xc(i)} y={H - 5} textAnchor="middle" fontSize="9" fill="var(--fg)">{(d.el_kwh || 0).toFixed(0)}</text>
          </g>);
      })}
    </svg>
  );
}

export default function HeatPump() {
  const [locs, setLocs] = useState([]);
  const [locId, setLocId] = useState(null);
  const [range, setRange] = useState("48h");
  const [series, setSeries] = useState([]);
  const [runs, setRuns] = useState([]);
  const [days, setDays] = useState([]);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.listLocalities().then(async (ls) => {
      setLocs(ls);
      for (const l of ls) {                       // první lokalita s TČ
        try { await api.hpState(l.id); setLocId(l.id); return; } catch {}
      }
      setErr("Žádná lokalita nemá modul tepelného čerpadla.");
    }).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => {
    if (!locId) return;
    let alive = true;
    const load = () => {
      api.hpSeries(locId, RANGES[range]).then((r) => alive && setSeries(r)).catch(() => {});
      api.hpRuns(locId, 100).then((r) => alive && setRuns(r)).catch(() => {});
      api.hpDaily(locId, 31).then((r) => alive && setDays(r)).catch(() => {});
    };
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [locId, range]);
  const dur = (r) => {
    const a = new Date(r.started_at), b = r.ended_at ? new Date(r.ended_at) : new Date();
    const m = Math.round((b - a) / 60000);
    return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
  };
  const fmtD = (iso) => new Date(iso).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <h1 style={{ margin: 0, fontSize: 20 }}>🌀 Tepelné čerpadlo</h1>
        {locs.length > 1 && (
          <select value={locId ?? ""} onChange={(e) => setLocId(Number(e.target.value))}>
            {locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>)}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {Object.keys(RANGES).map((k) => (
            <button key={k} className={`btn${range === k ? " primary" : ""}`} style={{ padding: "3px 10px", fontSize: 12 }}
                    onClick={() => setRange(k)}>{k}</button>))}
        </div>
      </div>
      {err && <p className="muted">{err}</p>}
      {locId && (<>
        <div className="panel" style={{ marginBottom: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>Teploty a běhy kompresoru</div>
          <TempChart rows={series} runs={runs} />
        </div>
        <div className="panel" style={{ marginBottom: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>Denní el. spotřeba (🟩 topení · 🟦 TUV) + COP</div>
          {days.length ? <DailyBars days={days.slice(-31)} /> : <p className="muted">Zatím žádné denní agregace.</p>}
        </div>
        <div className="panel">
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>Historie spínání</div>
          {runs.length ? (
            <table>
              <thead><tr><th>Start</th><th>Konec</th><th>Délka</th><th>Režim</th><th>T venk.</th><th>⚡ kWh</th><th>🔥 kWh</th></tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtD(r.started_at)}</td>
                    <td>{r.ended_at ? fmtD(r.ended_at) : <span style={{ color: "var(--green)" }}>● běží</span>}</td>
                    <td>{dur(r)}</td>
                    <td><span style={{ color: MODE_COLOR[r.mode] || "var(--fg)" }}>{MODE_CZ[r.mode] || r.mode}</span></td>
                    <td>{r.t_outdoor_start != null ? `${r.t_outdoor_start.toFixed(1)} °C` : "—"}</td>
                    <td>{(r.el_kwh ?? 0).toFixed(1)}</td>
                    <td>{(r.heat_kwh ?? 0).toFixed(1)}</td>
                  </tr>))}
              </tbody>
            </table>
          ) : <p className="muted">Zatím žádné běhy — první se zapíše, až kompresor příště nastartuje.</p>}
        </div>
      </>)}
    </div>
  );
}
