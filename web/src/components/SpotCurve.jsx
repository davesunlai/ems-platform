const GREEN = "#3fb950";
const RED = "#e06c75";

export default function SpotCurve({ curve, rules = [] }) {
  const today = curve?.today || [];
  const tomorrow = curve?.tomorrow || [];
  if (!today.length && !tomorrow.length)
    return <p className="muted" style={{ fontSize: 13 }}>Cenová křivka zatím není k dispozici (zítřek bývá po ~14:00).</p>;

  const slots = [
    ...today.map((h) => ({ ...h, day: "dnes" })),
    ...tomorrow.map((h) => ({ ...h, day: "zítra" })),
  ];
  const chargeThr = rules.filter((r) => r.enabled && r.type === "spot_charge").map((r) => Number(r.params.price_threshold));
  const dischThr = rules.filter((r) => r.enabled && r.type === "spot_discharge").map((r) => Number(r.params.price_threshold));

  const prices = slots.map((s) => s.price);
  const vals = [...prices, ...chargeThr, ...dischThr, 0];
  const maxV = Math.max(...vals), minV = Math.min(...vals);
  const span = (maxV - minV) || 1;

  const W = 960, H = 250, padT = 14, padB = 46, padL = 50, padR = 12;
  const plotH = H - padT - padB, plotW = W - padL - padR;
  const n = slots.length, bw = plotW / n;
  const y = (v) => padT + plotH * (1 - (v - minV) / span);
  const curHour = new Date().getHours();

  const barColor = (p) => {
    if (chargeThr.some((t) => p < t)) return GREEN;
    if (dischThr.some((t) => p > t)) return RED;
    return "var(--border)";
  };

  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 640 }}>
        {/* jednotka osy Y */}
        <text x={13} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="var(--muted)"
              transform={`rotate(-90 13 ${padT + plotH / 2})`}>Kč/MWh</text>
        {/* osa Y: min/max/0 */}
        {[minV, maxV, 0].filter((v, i, a) => a.indexOf(v) === i).map((v, i) => (
          <g key={i}>
            <line x1={padL} y1={y(v)} x2={W - padR} y2={y(v)} stroke="var(--border)" strokeWidth="0.5" opacity="0.4" />
            <text x={padL - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted)">{Math.round(v)}</text>
          </g>
        ))}

        {/* prahové čáry pravidel */}
        {chargeThr.map((t, i) => (
          <line key={`c${i}`} x1={padL} y1={y(t)} x2={W - padR} y2={y(t)} stroke={GREEN} strokeWidth="1" strokeDasharray="4 3" opacity="0.6" />
        ))}
        {dischThr.map((t, i) => (
          <line key={`d${i}`} x1={padL} y1={y(t)} x2={W - padR} y2={y(t)} stroke={RED} strokeWidth="1" strokeDasharray="4 3" opacity="0.6" />
        ))}

        {/* sloupce */}
        {slots.map((s, i) => {
          const x = padL + i * bw;
          const top = y(s.price), base = y(Math.min(0, minV) < 0 ? 0 : minV);
          const h = Math.max(1, Math.abs(base - top));
          const isCur = s.day === "dnes" && s.hour === curHour;
          return (
            <g key={i}>
              <rect x={x + 1} y={Math.min(top, base)} width={Math.max(1, bw - 1.5)} height={h}
                    fill={barColor(s.price)} opacity={s.day === "zítra" ? 0.65 : 1}
                    stroke={isCur ? "var(--fg)" : "none"} strokeWidth={isCur ? 1.5 : 0}>
                <title>{`${s.day} ${s.hour}:00 — ${Math.round(s.price)} Kč/MWh`}</title>
              </rect>
            </g>
          );
        })}

        {/* osa X: hodiny (po 6 h) */}
        {slots.map((s, i) => (s.hour % 6 === 0 ? (
          <text key={`hx${i}`} x={padL + i * bw + bw / 2} y={H - 28} textAnchor="middle"
                fontSize="9" fill="var(--muted)">{s.hour}</text>
        ) : null))}

        {/* předěl dnes | zítra + popisky */}
        {today.length > 0 && tomorrow.length > 0 && (
          <line x1={padL + today.length * bw} y1={padT} x2={padL + today.length * bw} y2={H - padB}
                stroke="var(--fg)" strokeWidth="0.7" opacity="0.5" strokeDasharray="2 2" />
        )}
        {today.length > 0 && (
          <text x={padL + (today.length * bw) / 2} y={H - 10} textAnchor="middle" fontSize="11" fill="var(--muted)">dnes</text>
        )}
        {tomorrow.length > 0 && (
          <text x={padL + today.length * bw + (tomorrow.length * bw) / 2} y={H - 10} textAnchor="middle" fontSize="11" fill="var(--muted)">zítra</text>
        )}
      </svg>
      <div style={{ display: "flex", gap: 18, fontSize: 12, color: "var(--muted)", marginTop: 4, flexWrap: "wrap" }}>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: GREEN, borderRadius: 2, marginRight: 5 }} />nabíjení (cena pod prahem)</span>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: RED, borderRadius: 2, marginRight: 5 }} />vybíjení do sítě (cena nad prahem)</span>
        <span>přerušované čáry = prahy pravidel · zítřek světlejší</span>
      </div>
    </div>
  );
}
