import { useEffect, useMemo, useState } from "react";
import { api } from "../api";

const PV = "#3fb950", BAND = "rgba(63,185,80,0.16)", LOAD = "#e3b341", SPOT = "#58a6ff";

export default function ForecastChart({ localityId }) {
  const [data, setData] = useState(null);
  const [hov, setHov] = useState(null);

  useEffect(() => {
    if (!localityId) return;
    let alive = true;
    const load = () => api.forecastData(localityId).then((r) => alive && setData(r)).catch(() => {});
    load();
    const t = setInterval(load, 300000);
    return () => { alive = false; clearInterval(t); };
  }, [localityId]);

  const avg = data?.pv?.avg || [];
  const loadS = data?.load || [];
  const spot = data?.spot || [];
  const fixed = (data?.pricing_mode || "spot") === "tariff";

  const geom = useMemo(() => {
    if (avg.length < 2) return null;
    const ms = (s) => new Date(s).getTime();
    const all = [...avg.map((p) => ms(p.ts)), ...loadS.map((p) => ms(p.ts)), ...spot.map((p) => ms(p.ts))];
    const t0 = Math.min(...all), t1 = Math.max(...all), tspan = t1 - t0 || 1;
    const kwMax = Math.max(1, ...avg.map((p) => (p.pv_w_hi ?? p.pv_w) / 1000), ...loadS.map((p) => p.load_w / 1000)) * 1.1;
    const spotVals = spot.map((p) => p.czk_mwh / 1000);
    const sLo = Math.min(0, ...(spotVals.length ? spotVals : [0]));
    const sHi = Math.max(1, ...(spotVals.length ? spotVals : [1]));
    const W = 760, H = 260, padL = 46, padR = 52, padT = 14, padB = 28;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const X = (t) => padL + ((t - t0) / tspan) * plotW;
    const Yk = (kw) => padT + plotH * (1 - kw / kwMax);
    const Ys = (cz) => padT + plotH * (1 - (cz - sLo) / ((sHi - sLo) || 1));
    return { ms, t0, t1, tspan, kwMax, sLo, sHi, W, H, padL, padR, padT, padB, plotW, plotH, X, Yk, Ys };
  }, [avg, loadS, spot]);

  if (!localityId) return null;
  if (!data) return <div className="muted" style={{ fontSize: 12, padding: "16px 0" }}>Načítám predikci…</div>;
  if (!geom) return <div className="muted" style={{ fontSize: 12, padding: "16px 0" }}>Zatím bez predikce — zadej polohu a panely v Lokalitách a dej Přepočítat.</div>;

  const { ms, X, Yk, Ys, W, H, padL, padR, padT, plotH, kwMax, sLo, sHi } = geom;
  const line = (pts, fy) => pts.map((p, i) => `${i ? "L" : "M"}${X(ms(p.ts)).toFixed(1)},${fy(p).toFixed(1)}`).join(" ");

  // pásmo nejistoty (lo nahoru, hi dolů)
  const bandTop = avg.map((p) => `${X(ms(p.ts)).toFixed(1)},${Yk((p.pv_w_hi ?? p.pv_w) / 1000).toFixed(1)}`);
  const bandBot = avg.slice().reverse().map((p) => `${X(ms(p.ts)).toFixed(1)},${Yk((p.pv_w_lo ?? p.pv_w) / 1000).toFixed(1)}`);
  const bandPath = `M${bandTop.join(" L")} L${bandBot.join(" L")} Z`;

  const nowX = X(Date.now());
  const showNow = Date.now() >= geom.t0 && Date.now() <= geom.t1;

  // osa X: po 6 h
  const ticks = [];
  for (let t = Math.ceil(geom.t0 / 36e5) * 36e5; t <= geom.t1; t += 6 * 36e5) ticks.push(t);
  const fmtX = (t) => { const d = new Date(t); return `${["ne","po","út","st","čt","pá","so"][d.getDay()]} ${String(d.getHours()).padStart(2,"0")}`; };

  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - r.left) * (W / r.width);
    const t = geom.t0 + ((x - padL) / geom.plotW) * geom.tspan;
    if (t < geom.t0 || t > geom.t1) { setHov(null); return; }
    const near = (arr) => arr.reduce((b, p) => Math.abs(ms(p.ts) - t) < Math.abs(ms(b.ts) - t) ? p : b, arr[0]);
    setHov({ t, pv: avg.length ? near(avg) : null, load: loadS.length ? near(loadS) : null, spot: spot.length ? near(spot) : null });
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 14, fontSize: 12, marginBottom: 4, flexWrap: "wrap" }}>
        <span style={{ color: PV }}>▬ výroba (avg)</span>
        <span className="muted">▨ pásmo nejistoty</span>
        <span style={{ color: LOAD }}>▬ spotřeba</span>
        <span style={{ color: SPOT }}>▬ spot {fixed ? "(jen orientačně)" : ""}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}
           onMouseMove={onMove} onMouseLeave={() => setHov(null)}>
        {/* osy kW (vlevo) */}
        {[0, 0.25, 0.5, 0.75, 1].map((f, i) => {
          const y = padT + plotH * (1 - f);
          return <g key={i}>
            <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="var(--border)" strokeWidth="0.5" opacity="0.5" />
            <text x={padL - 5} y={y + 3} textAnchor="end" fontSize="10" fill="var(--muted,#8b949e)">{(kwMax * f).toFixed(0)}</text>
            <text x={W - padR + 5} y={y + 3} fontSize="10" fill={SPOT}>{(sLo + (sHi - sLo) * f).toFixed(1)}</text>
          </g>;
        })}
        <text x={padL - 5} y={padT - 3} textAnchor="end" fontSize="9" fill="var(--muted,#8b949e)">kW</text>
        <text x={W - padR + 5} y={padT - 3} fontSize="9" fill={SPOT}>Kč/kWh</text>

        {/* pásmo + výroba */}
        <path d={bandPath} fill={BAND} stroke="none" />
        <path d={line(avg, (p) => Yk(p.pv_w / 1000))} fill="none" stroke={PV} strokeWidth="1.8" />
        {/* spotřeba */}
        {loadS.length >= 2 && <path d={line(loadS, (p) => Yk(p.load_w / 1000))} fill="none" stroke={LOAD} strokeWidth="1.5" />}
        {/* spot (pravá osa) */}
        {spot.length >= 2 && <path d={line(spot, (p) => Ys(p.czk_mwh / 1000))} fill="none" stroke={SPOT}
              strokeWidth="1.5" strokeDasharray={fixed ? "4 3" : "none"} opacity={fixed ? 0.6 : 1} />}

        {/* teď */}
        {showNow && <line x1={nowX} y1={padT} x2={nowX} y2={padT + plotH} stroke="#fff" strokeWidth="1" strokeDasharray="3 3" opacity="0.5" />}

        {/* x ticky */}
        {ticks.map((t, i) => (
          <text key={i} x={X(t)} y={H - 8} textAnchor="middle" fontSize="9" fill="var(--muted,#8b949e)">{fmtX(t)}</text>
        ))}

        {/* hover */}
        {hov && <line x1={X(hov.t)} y1={padT} x2={X(hov.t)} y2={padT + plotH} stroke="#fff" strokeWidth="0.5" opacity="0.4" />}
      </svg>
      {hov && (
        <div className="muted" style={{ fontSize: 12, display: "flex", gap: 12, flexWrap: "wrap" }}>
          <span>{new Date(hov.t).toLocaleString("cs-CZ", { weekday: "short", hour: "2-digit", minute: "2-digit" })}</span>
          {hov.pv && <span style={{ color: PV }}>výroba {(hov.pv.pv_w / 1000).toFixed(1)} kW</span>}
          {hov.load && <span style={{ color: LOAD }}>spotřeba {(hov.load.load_w / 1000).toFixed(1)} kW</span>}
          {hov.spot && <span style={{ color: SPOT }}>spot {(hov.spot.czk_mwh / 1000).toFixed(2)} Kč/kWh</span>}
        </div>
      )}
    </div>
  );
}
