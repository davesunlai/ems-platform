import { useEffect, useMemo, useState } from "react";
import { api } from "../api";

// I3/I2/I1 master H/S/D, I4/I5 slave H/D, I14 ambient
const TANKS = [
  { k: "tank_m_top", label: "Master horní (I3)", color: "#e0533d" },
  { k: "tank_m_mid", label: "Master střed (I2)", color: "#e8833a" },
  { k: "tank_m_bot", label: "Master dolní (I1)", color: "#e8b13a" },
  { k: "tank_s_top", label: "Slave horní (I4)", color: "#4a9ed8" },
  { k: "tank_s_bot", label: "Slave dolní (I5)", color: "#6f7bd8" },
];
const AMBIENT = { k: "temp_ambient", label: "Okolí (I14)", color: "#8b949e" };
const ALL = [...TANKS.map((t) => t.k), AMBIENT.k];
const RANGES = [{ l: "12 h", m: 720 }, { l: "24 h", m: 1440 }, { l: "3 dny", m: 4320 }, { l: "7 dní", m: 10080 }];

export default function TempChart({ localityId, deviceIds }) {
  const [data, setData] = useState(null);
  const [minutes, setMinutes] = useState(1440);
  const [hov, setHov] = useState(null);

  useEffect(() => {
    if (!localityId || !deviceIds?.length) return;
    let alive = true;
    const load = () => api.aggregate(deviceIds, ALL, minutes).then((r) => alive && setData(r.metrics || {})).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [localityId, (deviceIds || []).join(","), minutes]);

  const series = useMemo(() => {
    if (!data) return null;
    const map = {};
    let any = false;
    for (const k of ALL) {
      const pts = (data[k] || []).map((p) => ({ t: new Date(p.time).getTime(), v: p.value })).filter((p) => Number.isFinite(p.v));
      map[k] = pts;
      if (k !== AMBIENT.k && pts.length) any = true;
    }
    return any ? map : null;
  }, [data]);

  const geom = useMemo(() => {
    if (!series) return null;
    const tankPts = TANKS.flatMap((t) => series[t.k] || []);
    if (tankPts.length < 2) return null;
    const allT = ALL.flatMap((k) => series[k] || []).map((p) => p.t);
    const t0 = Math.min(...allT), t1 = Math.max(...allT), tspan = t1 - t0 || 1;
    // měřítko °C jen z nádrží (ambient ho nedeformuje)
    let lo = Math.min(...tankPts.map((p) => p.v)), hi = Math.max(...tankPts.map((p) => p.v));
    const pad = Math.max(2, (hi - lo) * 0.1); lo -= pad; hi += pad;
    const W = 760, H = 240, padL = 40, padR = 16, padT = 12, padB = 26;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const X = (t) => padL + ((t - t0) / tspan) * plotW;
    const Y = (c) => padT + plotH * (1 - (c - lo) / ((hi - lo) || 1));
    return { t0, t1, tspan, lo, hi, W, H, padL, padR, padT, padB, plotW, plotH, X, Y };
  }, [series]);

  if (!localityId || !deviceIds?.length) return null;
  if (!series || !geom) return null; // bez čidel teplot nic nezobrazuj

  const { X, Y, W, H, padL, padR, padT, plotH, lo, hi, t0, t1 } = geom;
  const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ");
  const last = (k) => { const a = series[k]; return a && a.length ? a[a.length - 1].v : null; };

  const ticks = [];
  const step = (t1 - t0) > 3 * 864e5 ? 24 : 6;
  for (let t = Math.ceil(t0 / (step * 36e5)) * step * 36e5; t <= t1; t += step * 36e5) ticks.push(t);
  const fmtX = (t) => { const d = new Date(t); return step >= 24 ? `${["ne","po","út","st","čt","pá","so"][d.getDay()]} ${d.getDate()}.` : `${["ne","po","út","st","čt","pá","so"][d.getDay()]} ${String(d.getHours()).padStart(2,"0")}`; };

  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - r.left) * (W / r.width);
    const t = t0 + ((x - padL) / geom.plotW) * geom.tspan;
    if (t < t0 || t > t1) { setHov(null); return; }
    const near = (arr) => arr.length ? arr.reduce((b, p) => Math.abs(p.t - t) < Math.abs(b.t - t) ? p : b, arr[0]) : null;
    const vals = {}; for (const k of ALL) vals[k] = near(series[k] || []);
    setHov({ t, vals });
  };

  return (
    <div className="card" style={{ marginTop: 14 }} id="teploty-aku">
      <h3 style={{ margin: "0 0 6px", fontSize: 15 }}>🌡️ Teploty AKU</h3>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", gap: 12, fontSize: 12, flexWrap: "wrap" }}>
          {TANKS.map((t) => (
            <span key={t.k} style={{ color: t.color }}>▬ {t.label}{last(t.k) != null && ` ${last(t.k).toFixed(1)}°`}</span>
          ))}
          <span style={{ color: AMBIENT.color }}>┄ {AMBIENT.label}{last(AMBIENT.k) != null && ` ${last(AMBIENT.k).toFixed(1)}°`}</span>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {RANGES.map((r) => (
            <button key={r.m} className="btn" onClick={() => setMinutes(r.m)}
                    style={{ padding: "2px 8px", fontSize: 11, opacity: minutes === r.m ? 1 : 0.55 }}>{r.l}</button>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} onMouseMove={onMove} onMouseLeave={() => setHov(null)}>
        {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
          const y = padT + plotH * (1 - f);
          return <g key={i}>
            <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="var(--border)" strokeWidth="0.5" opacity="0.5" />
            <text x={padL - 5} y={y + 3} textAnchor="end" fontSize="10" fill="var(--muted,#8b949e)">{(lo + (hi - lo) * f).toFixed(0)}</text>
          </g>;
        })}
        <text x={padL - 5} y={padT - 2} textAnchor="end" fontSize="9" fill="var(--muted,#8b949e)">°C</text>

        {/* nádrže */}
        {TANKS.map((t) => (series[t.k]?.length >= 2) && (
          <path key={t.k} d={path(series[t.k])} fill="none" stroke={t.color} strokeWidth="1.6" />
        ))}
        {/* ambient – čárkovaně, mimo měřítko (může klipovat) */}
        {series[AMBIENT.k]?.length >= 2 && (
          <path d={path(series[AMBIENT.k])} fill="none" stroke={AMBIENT.color} strokeWidth="1.3" strokeDasharray="4 3" opacity="0.85" />
        )}

        {ticks.map((t, i) => <text key={i} x={X(t)} y={H - 8} textAnchor="middle" fontSize="9" fill="var(--muted,#8b949e)">{fmtX(t)}</text>)}
        {hov && <line x1={X(hov.t)} y1={padT} x2={X(hov.t)} y2={padT + plotH} stroke="#fff" strokeWidth="0.5" opacity="0.4" />}
      </svg>
      {hov && (
        <div className="muted" style={{ fontSize: 11.5, display: "flex", gap: 10, flexWrap: "wrap" }}>
          <span>{new Date(hov.t).toLocaleString("cs-CZ", { weekday: "short", hour: "2-digit", minute: "2-digit" })}</span>
          {TANKS.map((t) => hov.vals[t.k] && <span key={t.k} style={{ color: t.color }}>{hov.vals[t.k].v.toFixed(1)}°</span>)}
          {hov.vals[AMBIENT.k] && <span style={{ color: AMBIENT.color }}>okolí {hov.vals[AMBIENT.k].v.toFixed(1)}°</span>}
        </div>
      )}
    </div>
  );
}
