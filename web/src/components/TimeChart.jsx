// Spojnicový graf s osami: X = čas, Y = hodnota (s popisky).
// Bez externích knihoven. Hodnoty ve W se zobrazují jako kW.
// Hover: svislá čára u kurzoru + bublina s časem a hodnotou.
import { useState } from "react";

export default function TimeChart({ points, color = "#3fb950", unit = "", height = 220 }) {
  const [hov, setHov] = useState(null);
  if (!points || points.length < 2)
    return <div className="muted" style={{ fontSize: 12, padding: "20px 0" }}>Sbírám data…</div>;

  const toKW = unit === "W" || unit === "var";
  const disp = (v) => (toKW ? v / 1000 : v);
  const dispUnit = unit === "W" ? "kW" : unit === "var" ? "kvar" : unit;

  const vals = points.map((p) => disp(p.value));
  let lo = Math.min(...vals), hi = Math.max(...vals);
  lo = Math.min(0, lo); hi = Math.max(0, hi);          // ať je 0 vidět
  if (hi === lo) hi = lo + 1;
  const span = hi - lo;

  const ts = points.map((p) => new Date(p.time).getTime());
  const t0 = ts[0], t1 = ts[ts.length - 1];
  const tspan = t1 - t0 || 1;

  const W = 760, H = height, padL = 52, padR = 12, padT = 12, padB = 26;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const X = (t) => padL + ((t - t0) / tspan) * plotW;
  const Y = (v) => padT + plotH * (1 - (v - lo) / span);

  const d = points.map((p, i) => `${i ? "L" : "M"}${X(ts[i]).toFixed(1)},${Y(disp(p.value)).toFixed(1)}`).join(" ");
  const area = `${d} L${X(t1).toFixed(1)},${Y(lo).toFixed(1)} L${X(t0).toFixed(1)},${Y(lo).toFixed(1)} Z`;
  const gid = "tc" + color.replace("#", "");

  const fmtY = (v) => {
    if (dispUnit === "%") return Math.round(v);
    if (Math.abs(v) >= 100) return Math.round(v);
    if (Math.abs(v) >= 10) return v.toFixed(1);
    return v.toFixed(2);
  };
  const multiDay = tspan > 2 * 864e5;
  const fmtX = (t) => {
    const dt = new Date(t);
    return multiDay
      ? dt.toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })
      : dt.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  };
  const fmtFull = (t) => new Date(t).toLocaleString("cs-CZ",
    { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

  const yTicks = [lo, lo + span / 2, hi];
  const xN = 5;
  const xTicks = Array.from({ length: xN }, (_, i) => t0 + (tspan * i) / (xN - 1));

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const vbX = ((e.clientX - rect.left) / rect.width) * W;
    if (vbX < padL || vbX > W - padR) { setHov(null); return; }
    const tH = t0 + ((vbX - padL) / plotW) * tspan;
    let best = 0, bd = Infinity;
    for (let i = 0; i < ts.length; i++) { const dd = Math.abs(ts[i] - tH); if (dd < bd) { bd = dd; best = i; } }
    setHov(best);
  };

  const hx = hov != null ? X(ts[hov]) : 0;
  const hy = hov != null ? Y(disp(points[hov].value)) : 0;

  return (
    <div style={{ position: "relative" }} onMouseMove={onMove} onMouseLeave={() => setHov(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <defs>
          <linearGradient id={gid} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.26" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>

        {yTicks.map((v, i) => (
          <g key={`y${i}`}>
            <line x1={padL} y1={Y(v)} x2={W - padR} y2={Y(v)} stroke="var(--border)" strokeWidth="0.5" opacity="0.45" />
            <text x={padL - 7} y={Y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted)">{fmtY(v)}</text>
          </g>
        ))}
        <text x={14} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="var(--muted)"
              transform={`rotate(-90 14 ${padT + plotH / 2})`}>{dispUnit}</text>

        {xTicks.map((t, i) => (
          <text key={`x${i}`} x={X(t)} y={H - 8}
                textAnchor={i === 0 ? "start" : i === xN - 1 ? "end" : "middle"}
                fontSize="10" fill="var(--muted)">{fmtX(t)}</text>
        ))}
        <line x1={padL} y1={padT + plotH} x2={W - padR} y2={padT + plotH} stroke="var(--border)" strokeWidth="0.8" />

        <path d={area} fill={`url(#${gid})`} />
        <path d={d} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />

        {hov != null && (
          <g>
            <line x1={hx} y1={padT} x2={hx} y2={padT + plotH} stroke="var(--muted)" strokeWidth="0.8" strokeDasharray="3 3" />
            <circle cx={hx} cy={hy} r="3.2" fill={color} stroke="var(--panel, #161b22)" strokeWidth="1.5" />
          </g>
        )}
      </svg>

      {hov != null && (
        <div style={{
          position: "absolute", top: 4, left: `${(hx / W) * 100}%`, transform: "translateX(-50%)",
          background: "var(--panel, #161b22)", border: "1px solid var(--border, #30363d)", borderRadius: 7,
          padding: "5px 9px", fontSize: 12, whiteSpace: "nowrap", pointerEvents: "none", zIndex: 5,
          boxShadow: "0 4px 14px rgba(0,0,0,.4)" }}>
          <div className="muted" style={{ fontSize: 11 }}>{fmtFull(ts[hov])}</div>
          <div><strong>{fmtY(disp(points[hov].value))}</strong> {dispUnit}</div>
        </div>
      )}
    </div>
  );
}
