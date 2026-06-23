// Víceřadý spojnicový graf s osami (čas X, výkon Y v kW) + klikací legenda.
// series: [{ label, color, points: [{time, value}] }] — hodnoty ve W → kW.
// Hover: svislá čára u kurzoru + bublina s hodnotou viditelných řad.
// Klik na popisek v legendě řadu skryje/zobrazí (přepočte i osu Y).
import { useState } from "react";

export default function MultiChart({ series, height = 240 }) {
  const [hovT, setHovT] = useState(null);
  const [hovY, setHovY] = useState(0.15);
  const [hidden, setHidden] = useState(() => new Set());
  const valid = (series || []).filter((s) => s.points && s.points.length >= 2);
  if (!valid.length)
    return <div className="muted" style={{ fontSize: 12, padding: "20px 0" }}>Zatím bez dat v tomto okně.</div>;

  const shown = valid.filter((s) => !hidden.has(s.label));
  const toggle = (label) => setHidden((h) => {
    const n = new Set(h);
    n.has(label) ? n.delete(label) : n.add(label);
    return n;
  });

  const disp = (v) => v / 1000; // W → kW
  const allVals = shown.flatMap((s) => s.points.map((p) => disp(p.value)));
  let lo = Math.min(0, ...(allVals.length ? allVals : [0]));
  let hi = Math.max(0, ...(allVals.length ? allVals : [1]));
  if (hi === lo) hi = lo + 1;
  const span = hi - lo;

  const baseTs = (shown.length ? shown : valid).flatMap((s) => s.points.map((p) => new Date(p.time).getTime()));
  const t0 = Math.min(...baseTs), t1 = Math.max(...baseTs);
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
  const fmtFull = (t) => new Date(t).toLocaleString("cs-CZ",
    { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const yTicks = [...new Set([lo, lo + span / 2, hi, 0])].sort((a, b) => a - b);
  const xN = 5;
  const xTicks = Array.from({ length: xN }, (_, i) => t0 + (tspan * i) / (xN - 1));

  const pathFor = (pts) => pts.map((p, i) =>
    `${i ? "L" : "M"}${X(new Date(p.time).getTime()).toFixed(1)},${Y(disp(p.value)).toFixed(1)}`).join(" ");

  const nearest = (pts, t) => {
    let best = pts[0], bd = Infinity;
    for (const p of pts) { const dd = Math.abs(new Date(p.time).getTime() - t); if (dd < bd) { bd = dd; best = p; } }
    return best;
  };

  const onMove = (e) => {
    if (!shown.length) { setHovT(null); return; }
    const rect = e.currentTarget.getBoundingClientRect();
    const vbX = ((e.clientX - rect.left) / rect.width) * W;
    if (vbX < padL || vbX > W - padR) { setHovT(null); return; }
    setHovT(t0 + ((vbX - padL) / plotW) * tspan);
    setHovY((e.clientY - rect.top) / rect.height);     // 0..1 svislá poloha kurzoru
  };

  const hx = hovT != null ? X(hovT) : 0;
  const hoverRows = hovT != null ? shown.map((s) => ({ label: s.label, color: s.color, p: nearest(s.points, hovT) })) : [];

  return (
    <div>
      <div style={{ position: "relative" }} onMouseMove={onMove} onMouseLeave={() => setHovT(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
          <text x={14} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="var(--muted)"
                transform={`rotate(-90 14 ${padT + plotH / 2})`}>kW</text>
          {yTicks.map((v, i) => (
            <g key={i}>
              <line x1={padL} y1={Y(v)} x2={W - padR} y2={Y(v)} stroke="var(--border)" strokeWidth="0.5" opacity="0.45" />
              <text x={padL - 7} y={Y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted)" fontWeight={v === 0 ? 700 : 400}>{fmtY(v)}</text>
            </g>
          ))}
          {/* výrazná osa X (nulová linka) */}
          <line x1={padL} y1={Y(0)} x2={W - padR} y2={Y(0)} stroke="var(--fg, #c9d1d9)" strokeWidth="1.4" opacity="0.85" />
          {xTicks.map((t, i) => (
            <text key={`x${i}`} x={X(t)} y={H - 8}
                  textAnchor={i === 0 ? "start" : i === xN - 1 ? "end" : "middle"}
                  fontSize="10" fill="var(--muted)">{fmtX(t)}</text>
          ))}
          <line x1={padL} y1={padT + plotH} x2={W - padR} y2={padT + plotH} stroke="var(--border)" strokeWidth="0.8" />
          {shown.map((s, i) => (
            <path key={i} d={pathFor(s.points)} fill="none" stroke={s.color} strokeWidth="1.7" vectorEffect="non-scaling-stroke" />
          ))}

          {hovT != null && shown.length > 0 && (
            <g>
              <line x1={hx} y1={padT} x2={hx} y2={padT + plotH} stroke="var(--muted)" strokeWidth="0.8" strokeDasharray="3 3" />
              {hoverRows.map((r, i) => (
                <circle key={i} cx={hx} cy={Y(disp(r.p.value))} r="3" fill={r.color} stroke="var(--panel, #161b22)" strokeWidth="1.3" />
              ))}
            </g>
          )}
        </svg>

        {hovT != null && shown.length > 0 && (
          <div style={{
            position: "absolute", top: `${Math.max(2, Math.min(58, hovY * 100 - 10))}%`, left: `${(hx / W) * 100}%`, transform: "translateX(-50%)",
            background: "var(--panel, #161b22)", border: "1px solid var(--border, #30363d)", borderRadius: 7,
            padding: "6px 10px", fontSize: 12, whiteSpace: "nowrap", pointerEvents: "none", zIndex: 5,
            boxShadow: "0 4px 14px rgba(0,0,0,.4)" }}>
            <div className="muted" style={{ fontSize: 11, marginBottom: 3 }}>{fmtFull(hovT)}</div>
            {hoverRows.map((r, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ display: "inline-block", width: 9, height: 3, background: r.color }} />
                <span className="muted">{r.label}</span>
                <strong style={{ marginLeft: "auto", paddingLeft: 10 }}>{fmtY(disp(r.p.value))} kW</strong>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 14, fontSize: 12, color: "var(--muted)", marginTop: 4, flexWrap: "wrap" }}>
        {valid.map((s, i) => {
          const off = hidden.has(s.label);
          return (
            <span key={i} onClick={() => toggle(s.label)} title="Klikni pro skrytí/zobrazení"
              style={{ cursor: "pointer", userSelect: "none", opacity: off ? 0.4 : 1 }}>
              <span style={{ display: "inline-block", width: 12, height: 3, background: s.color, marginRight: 6, verticalAlign: "middle" }} />
              <span style={{ textDecoration: off ? "line-through" : "none" }}>{s.label}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}
