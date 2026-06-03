// Spojnicový graf s osami: X = čas, Y = hodnota (s popisky).
// Bez externích knihoven. Hodnoty ve W se zobrazují jako kW.
export default function TimeChart({ points, color = "#3fb950", unit = "", height = 220 }) {
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

  const yTicks = [lo, lo + span / 2, hi];
  const xN = 5;
  const xTicks = Array.from({ length: xN }, (_, i) => t0 + (tspan * i) / (xN - 1));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
      <defs>
        <linearGradient id={gid} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.26" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* osa Y: mřížka + popisky */}
      {yTicks.map((v, i) => (
        <g key={`y${i}`}>
          <line x1={padL} y1={Y(v)} x2={W - padR} y2={Y(v)} stroke="var(--border)" strokeWidth="0.5" opacity="0.45" />
          <text x={padL - 7} y={Y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted)">{fmtY(v)}</text>
        </g>
      ))}
      {/* jednotka osy Y */}
      <text x={14} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="var(--muted)"
            transform={`rotate(-90 14 ${padT + plotH / 2})`}>{dispUnit}</text>

      {/* osa X: popisky času */}
      {xTicks.map((t, i) => (
        <text key={`x${i}`} x={X(t)} y={H - 8}
              textAnchor={i === 0 ? "start" : i === xN - 1 ? "end" : "middle"}
              fontSize="10" fill="var(--muted)">{fmtX(t)}</text>
      ))}
      <line x1={padL} y1={padT + plotH} x2={W - padR} y2={padT + plotH} stroke="var(--border)" strokeWidth="0.8" />

      {/* data */}
      <path d={area} fill={`url(#${gid})`} />
      <path d={d} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
