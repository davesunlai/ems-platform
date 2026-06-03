// Víceřadý spojnicový graf s osami (čas X, výkon Y v kW) + legenda.
// series: [{ label, color, points: [{time, value}] }] — hodnoty ve W → kW.
import { useRef, useState } from "react";

export default function MultiChart({ series, height = 240, onPan, windowMinutes }) {
  const drag = useRef(null);
  const [shift, setShift] = useState(0);
  const W0 = 760;
  const down = (e) => { drag.current = { x: e.clientX, w: e.currentTarget.getBoundingClientRect().width }; try { e.currentTarget.setPointerCapture(e.pointerId); } catch {} };
  const move = (e) => { if (drag.current) setShift(((e.clientX - drag.current.x) / drag.current.w) * W0); };
  const end = (e) => {
    if (!drag.current) return;
    const frac = (e.clientX - drag.current.x) / drag.current.w;
    drag.current = null; setShift(0);
    if (onPan && Math.abs(frac) > 0.02 && windowMinutes) onPan(frac * windowMinutes);
  };
  const valid = (series || []).filter((s) => s.points && s.points.length >= 2);
  if (!valid.length)
    return <div className="muted" style={{ fontSize: 12, padding: "20px 0" }}>Zatím bez dat v tomto okně.</div>;

  const disp = (v) => v / 1000; // W → kW
  const allVals = valid.flatMap((s) => s.points.map((p) => disp(p.value)));
  let lo = Math.min(0, ...allVals), hi = Math.max(0, ...allVals);
  if (hi === lo) hi = lo + 1;
  const span = hi - lo;

  const allTs = valid.flatMap((s) => s.points.map((p) => new Date(p.time).getTime()));
  const t0 = Math.min(...allTs), t1 = Math.max(...allTs);
  const tspan = t1 - t0 || 1;

  const W = 760, H = height, padL = 52, padR = 12, padT = 12, padB = 26;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const X = (t) => padL + ((t - t0) / tspan) * plotW;
  const Y = (v) => padT + plotH * (1 - (v - lo) / span);

  const fmtY = (v) => (Math.abs(v) >= 100 ? Math.round(v) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
  const multiDay = tspan > 2 * 864e5;
  const fmtX = (t) => {
    const d = new Date(t);
    return multiDay ? d.toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })
                    : d.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  };
  const yTicks = [lo, lo + span / 2, hi];
  const xN = 5;
  const xTicks = Array.from({ length: xN }, (_, i) => t0 + (tspan * i) / (xN - 1));

  const pathFor = (pts) => pts.map((p, i) =>
    `${i ? "L" : "M"}${X(new Date(p.time).getTime()).toFixed(1)},${Y(disp(p.value)).toFixed(1)}`).join(" ");

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", cursor: onPan ? "ew-resize" : "default", touchAction: "none" }}
           onPointerDown={onPan ? down : undefined} onPointerMove={onPan ? move : undefined}
           onPointerUp={onPan ? end : undefined} onPointerLeave={onPan ? end : undefined}>
        <text x={14} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="var(--muted)"
              transform={`rotate(-90 14 ${padT + plotH / 2})`}>kW</text>
        {yTicks.map((v, i) => (
          <g key={i}>
            <line x1={padL} y1={Y(v)} x2={W - padR} y2={Y(v)} stroke="var(--border)" strokeWidth="0.5" opacity="0.45" />
            <text x={padL - 7} y={Y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted)">{fmtY(v)}</text>
          </g>
        ))}
        {lo < 0 && hi > 0 && (
          <line x1={padL} y1={Y(0)} x2={W - padR} y2={Y(0)} stroke="var(--border)" strokeWidth="0.8" opacity="0.7" />
        )}
        {xTicks.map((t, i) => (
          <text key={`x${i}`} x={X(t)} y={H - 8}
                textAnchor={i === 0 ? "start" : i === xN - 1 ? "end" : "middle"}
                fontSize="10" fill="var(--muted)">{fmtX(t)}</text>
        ))}
        <line x1={padL} y1={padT + plotH} x2={W - padR} y2={padT + plotH} stroke="var(--border)" strokeWidth="0.8" />
        <g transform={`translate(${shift},0)`}>
          {valid.map((s, i) => (
            <path key={i} d={pathFor(s.points)} fill="none" stroke={s.color} strokeWidth="1.7" vectorEffect="non-scaling-stroke" />
          ))}
        </g>
      </svg>
      <div style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--muted)", marginTop: 4, flexWrap: "wrap" }}>
        {valid.map((s, i) => (
          <span key={i}><span style={{ display: "inline-block", width: 12, height: 3, background: s.color, marginRight: 6, verticalAlign: "middle" }} />{s.label}</span>
        ))}
      </div>
    </div>
  );
}
