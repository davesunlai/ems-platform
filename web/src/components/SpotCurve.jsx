import { useEffect, useState } from "react";
import { api } from "../api";

const GREEN = "#3fb950";
const RED = "#e06c75";
const WIN = [
  { days: 1, label: "den" }, { days: 2, label: "2 dny" }, { days: 3, label: "3 dny" },
  { days: 7, label: "7 dní" }, { days: 14, label: "14 dní" }, { days: 30, label: "30 dní" },
];

export default function SpotCurve({ rules = [] }) {
  const [wi, setWi] = useState(0);
  const [slots, setSlots] = useState(null);
  const [hov, setHov] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.spotCurve(WIN[wi].days).then((r) => alive && setSlots(r.slots)).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [wi]);

  const controls = (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
      <span style={{ flex: 1 }} />
      <button className="btn" style={{ padding: "2px 11px", fontSize: 16, lineHeight: 1 }}
              onClick={() => setWi((w) => Math.max(0, w - 1))} disabled={wi === 0} title="kratší">−</button>
      <span className="muted" style={{ minWidth: 50, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>{WIN[wi].label}</span>
      <button className="btn" style={{ padding: "2px 11px", fontSize: 16, lineHeight: 1 }}
              onClick={() => setWi((w) => Math.min(WIN.length - 1, w + 1))} disabled={wi === WIN.length - 1} title="delší (až 30 dní)">+</button>
    </div>
  );

  if (!slots) return <>{controls}<p className="muted" style={{ fontSize: 13 }}>Načítám…</p></>;
  if (!slots.length) return <>{controls}<p className="muted" style={{ fontSize: 13 }}>Data zatím nejsou (historie se plní; zítřek bývá po ~14:00).</p></>;

  const chargeThr = rules.filter((r) => r.enabled && r.type === "spot_charge").map((r) => Number(r.params.price_threshold));
  const dischThr = rules.filter((r) => r.enabled && r.type === "spot_discharge").map((r) => Number(r.params.price_threshold));

  const prices = slots.map((s) => s.price);
  const vals = [...prices, ...chargeThr, ...dischThr, 0];
  const maxV = Math.max(...vals), minV = Math.min(0, ...vals);   // ať je 0 vždy vidět (osa X)
  const span = (maxV - minV) || 1;

  const ts = slots.map((s) => new Date(s.start).getTime());
  const multiDay = WIN[wi].days > 2;
  const now = Date.now();

  const W = 960, H = 250, padT = 14, padB = 40, padL = 52, padR = 12;
  const plotH = H - padT - padB, plotW = W - padL - padR;
  const n = slots.length, bw = plotW / n;
  const y = (v) => padT + plotH * (1 - (v - minV) / span);
  const base = y(Math.min(0, minV) < 0 ? 0 : minV);

  const barColor = (p) => {
    if (chargeThr.some((t) => p < t)) return GREEN;
    if (dischThr.some((t) => p > t)) return RED;
    return "var(--border)";
  };
  const fmtX = (t) => {
    const d = new Date(t);
    return multiDay ? d.toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" })
                    : d.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  };

  // ~7 popisků osy X rovnoměrně
  const xN = Math.min(7, n);
  const xIdx = Array.from({ length: xN }, (_, i) => Math.round((i * (n - 1)) / (xN - 1)));
  // hranice dnů (svislé linky)
  const dayBounds = [];
  for (let i = 1; i < n; i++) if (new Date(ts[i]).getDate() !== new Date(ts[i - 1]).getDate()) dayBounds.push(i);
  // aktuální slot
  let curIdx = -1;
  for (let i = 0; i < n; i++) {
    const next = i + 1 < n ? ts[i + 1] : ts[i] + (ts[1] - ts[0] || 9e5);
    if (now >= ts[i] && now < next) { curIdx = i; break; }
  }

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const vbX = ((e.clientX - rect.left) / rect.width) * W;
    if (vbX < padL || vbX > W - padR) { setHov(null); return; }
    const i = Math.floor((vbX - padL) / bw);
    setHov(i >= 0 && i < n ? i : null);
  };
  const hx = hov != null ? padL + (hov + 0.5) * bw : 0;
  const fmtFull = (t) => new Date(t).toLocaleString("cs-CZ",
    { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

  return (
    <>
      {controls}
      <div style={{ position: "relative" }} onMouseMove={onMove} onMouseLeave={() => setHov(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", display: "block" }}>
        <text x={13} y={padT + plotH / 2} textAnchor="middle" fontSize="10" fill="var(--muted)"
              transform={`rotate(-90 13 ${padT + plotH / 2})`}>Kč/MWh</text>

        {[minV, maxV, 0].filter((v, i, a) => a.indexOf(v) === i).map((v, i) => (
          <g key={i}>
            <line x1={padL} y1={y(v)} x2={W - padR} y2={y(v)} stroke="var(--border)" strokeWidth="0.5" opacity="0.4" />
            <text x={padL - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted)" fontWeight={v === 0 ? 700 : 400}>{Math.round(v)}</text>
          </g>
        ))}
        {/* výrazná osa X (nulová linka) */}
        <line x1={padL} y1={y(0)} x2={W - padR} y2={y(0)} stroke="var(--fg, #c9d1d9)" strokeWidth="1.4" opacity="0.85" />

        {chargeThr.map((t, i) => (
          <line key={`c${i}`} x1={padL} y1={y(t)} x2={W - padR} y2={y(t)} stroke={GREEN} strokeWidth="1" strokeDasharray="4 3" opacity="0.6" />
        ))}
        {dischThr.map((t, i) => (
          <line key={`d${i}`} x1={padL} y1={y(t)} x2={W - padR} y2={y(t)} stroke={RED} strokeWidth="1" strokeDasharray="4 3" opacity="0.6" />
        ))}

        {dayBounds.map((i, k) => (
          <line key={`db${k}`} x1={padL + i * bw} y1={padT} x2={padL + i * bw} y2={padT + plotH}
                stroke="var(--fg)" strokeWidth="0.6" opacity="0.35" strokeDasharray="2 3" />
        ))}

        {slots.map((s, i) => {
          const top = y(s.price), h = Math.max(0.8, Math.abs(base - top));
          return (
            <rect key={i} x={padL + i * bw} y={Math.min(top, base)} width={Math.max(0.6, bw - 0.4)} height={h}
                  fill={barColor(s.price)} stroke={i === curIdx ? "var(--fg)" : "none"} strokeWidth={i === curIdx ? 1.2 : 0}>
              <title>{`${new Date(s.start).toLocaleString("cs-CZ")} — ${Math.round(s.price)} Kč/MWh`}</title>
            </rect>
          );
        })}

        {xIdx.map((i, k) => (
          <text key={`x${k}`} x={padL + i * bw + bw / 2} y={H - 8}
                textAnchor={k === 0 ? "start" : k === xIdx.length - 1 ? "end" : "middle"}
                fontSize="9.5" fill="var(--muted)">{fmtX(ts[i])}</text>
        ))}

        {hov != null && (
          <line x1={hx} y1={padT} x2={hx} y2={padT + plotH} stroke="var(--fg)" strokeWidth="0.9" strokeDasharray="3 3" opacity="0.8" />
        )}
      </svg>

      {hov != null && (
        <div style={{
          position: "absolute", top: 4, left: `${(hx / W) * 100}%`, transform: "translateX(-50%)",
          background: "var(--panel, #161b22)", border: "1px solid var(--border, #30363d)", borderRadius: 7,
          padding: "5px 9px", fontSize: 12, whiteSpace: "nowrap", pointerEvents: "none", zIndex: 5,
          boxShadow: "0 4px 14px rgba(0,0,0,.4)" }}>
          <div className="muted" style={{ fontSize: 11 }}>{fmtFull(slots[hov].start)}</div>
          <div><strong>{Math.round(slots[hov].price)}</strong> Kč/MWh</div>
        </div>
      )}
      </div>
      <div style={{ display: "flex", gap: 18, fontSize: 12, color: "var(--muted)", marginTop: 4, flexWrap: "wrap" }}>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: GREEN, borderRadius: 2, marginRight: 5 }} />nabíjení (pod prahem)</span>
        <span><span style={{ display: "inline-block", width: 10, height: 10, background: RED, borderRadius: 2, marginRight: 5 }} />vybíjení do sítě (nad prahem)</span>
        <span>15min intervaly · přerušované = prahy pravidel · zvýrazněn aktuální slot</span>
      </div>
    </>
  );
}
