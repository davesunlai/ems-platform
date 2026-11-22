import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import CursorBox, { CURSOR_LINE } from "./CursorBox";

// Detail jednoho článku: průběh napětí = uložená historie (1× za 5 min, při testu/balancování 1× za min)
// + živý úsek po 5 s za dobu, co je okno otevřené. Čárkovaně průměr bloku pro srovnání.
const CELL = "#e0602c";
const cs = (v, d = 0) => (v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toLocaleString("cs-CZ", { minimumFractionDigits: d, maximumFractionDigits: d }));
const RANGES = [[0, "jen živě"], [6, "6 h"], [24, "24 h"], [168, "7 dní"], [720, "30 dní"]];

function Chart({ P }) {
  const box = useRef(null);
  const [W, setW] = useState(820);
  const [cur, setCur] = useState(null), [pos, setPos] = useState(null);
  useEffect(() => { if (!box.current) return undefined; const ro = new ResizeObserver((e) => setW(Math.max(320, Math.round(e[0].contentRect.width)))); ro.observe(box.current); return () => ro.disconnect(); }, []);
  const n = P.t.length;
  if (n < 2) return <div ref={box} className="muted" style={{ padding: "30px 0", fontSize: 13 }}>Pro zvolené období zatím nejsou aspoň dva vzorky.</div>;
  const H = 250, padL = 56, padR = 84, padT = 12, padB = 26, pw = W - padL - padR, ph = H - padT - padB;
  const t0 = P.t[0], t1 = P.t[n - 1];
  let lo = Infinity, hi = -Infinity; for (let i = 0; i < n; i++) for (const v of [P.mv[i], P.avg[i]]) if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const padv = Math.max(3, (hi - lo) * 0.12); lo -= padv; hi += padv;
  const X = (t) => padL + ((t - t0) / (t1 - t0 || 1)) * pw, Y = (v) => padT + ph * (1 - (v - lo) / (hi - lo || 1));
  const stride = Math.max(1, Math.ceil(n / 1500));
  const path = (arr) => { let d = "", pen = false, ly = 0; for (let i = 0; i < n; i += stride) { const v = arr[i]; if (v == null) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${X(P.t[i]).toFixed(1)} ${Y(v).toFixed(1)}`; pen = true; ly = Y(v); } return [d, ly]; };
  const [dc, yc] = path(P.mv), [da, ya0] = path(P.avg); const ya = Math.abs(ya0 - yc) < 13 ? yc + (ya0 >= yc ? 13 : -13) : ya0;
  const span = t1 - t0, multi = span > 30 * 3600e3;
  const ticks = Array.from({ length: 6 }, (_, i) => t0 + (span * i) / 5);
  const fmt = (t) => { const d = new Date(t); return multi ? d.toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit", ...(span < 20 * 60e3 ? { second: "2-digit" } : {}) }); };
  const move = (e) => { const r = box.current.getBoundingClientRect(); const t = t0 + ((Math.max(padL, Math.min(padL + pw, e.clientX - r.left)) - padL) / pw) * span;
    let a = 0, b = n - 1; while (a < b) { const m = (a + b) >> 1; if (P.t[m] < t) a = m + 1; else b = m; }
    setCur(a > 0 && Math.abs(P.t[a - 1] - t) < Math.abs(P.t[a] - t) ? a - 1 : a); setPos({ x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height }); };
  return (
    <div ref={box} style={{ position: "relative", cursor: "crosshair" }} onMouseMove={move} onMouseLeave={() => { setCur(null); setPos(null); }}>
      <svg width={W} height={H} style={{ display: "block" }}>
        {[0, 0.25, 0.5, 0.75, 1].map((q) => { const v = lo + (hi - lo) * q; return <g key={q}><line x1={padL} x2={padL + pw} y1={Y(v)} y2={Y(v)} stroke="var(--border)" />
          <text x={padL - 6} y={Y(v) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{cs(v / 1000, 3)}</text></g>; })}
        {P.liveFrom != null && P.liveFrom > t0 && <g><rect x={X(P.liveFrom)} y={padT} width={padL + pw - X(P.liveFrom)} height={ph} fill="var(--green)" opacity={0.07} />
          <text x={X(P.liveFrom) + 4} y={padT + 12} fontSize={10.5} fill="var(--muted)">živě po 5 s</text></g>}
        <path d={da} fill="none" stroke="var(--fg)" strokeWidth={1.6} strokeDasharray="5 4" opacity={0.75} />
        <path d={dc} fill="none" stroke={CELL} strokeWidth={2} strokeLinejoin="round" />
        <circle cx={padL + pw + 7} cy={yc} r={4} fill={CELL} /><text x={padL + pw + 15} y={yc + 4} fontSize={11.5} fill="var(--fg)">článek</text>
        <circle cx={padL + pw + 7} cy={ya} r={4} fill="var(--fg)" /><text x={padL + pw + 15} y={ya + 4} fontSize={11.5} fill="var(--fg)">průměr</text>
        {ticks.map((t, i) => <text key={i} x={X(t)} y={H - 8} textAnchor={i === 0 ? "start" : i === 5 ? "end" : "middle"} fontSize={11} fill="var(--muted)">{fmt(t)}</text>)}
        {cur != null && <g><line x1={X(P.t[cur])} x2={X(P.t[cur])} y1={padT} y2={padT + ph} {...CURSOR_LINE} />
          {P.mv[cur] != null && <circle cx={X(P.t[cur])} cy={Y(P.mv[cur])} r={4.5} fill={CELL} stroke="var(--panel)" strokeWidth={2} />}</g>}
      </svg>
      {cur != null && <CursorBox pos={pos} width={210} height={90}>
        <b>{new Date(P.t[cur]).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</b>
        <div><span style={{ color: CELL }}>●</span> článek <b>{cs(P.mv[cur] / 1000, 3)} V</b></div>
        <div>průměr bloku {cs(P.avg[cur] / 1000, 3)} V · rozdíl {P.mv[cur] != null && P.avg[cur] != null ? `${P.mv[cur] - P.avg[cur] >= 0 ? "+" : ""}${cs(P.mv[cur] - P.avg[cur], 0)} mV` : "—"}</div>
        {P.temp[cur] != null && <div className="muted">teplota {cs(P.temp[cur] / 10, 1)} °C</div>}
      </CursorBox>}
    </div>);
}

export default function BmsCellDetail({ block, n, hist, energy, onClose }) {
  const c = block.cells, per = c.per_module;
  const [hours, setHours] = useState(6);
  const [stored, setStored] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let alive = true;
    setErr("");
    if (!hours) { setStored({ t: [], mv: [], temp: [], avg: [] }); return undefined; }
    const load = () => api.bmsCellHistory(block.module_id, n, hours).then((r) => alive && setStored(r)).catch((e) => alive && setErr(e.message));
    load();
    const h = setInterval(load, 60000);
    return () => { alive = false; clearInterval(h); };
  }, [block.module_id, n, hours]);
  const all = c.modules.flatMap((m) => m.mv), temps = c.modules.flatMap((m) => m.temp || []);
  const mv = all[n - 1], rank = [...all].sort((a, b) => b - a).indexOf(mv) + 1;
  const live = hist || [];
  const P = useMemo(() => {
    const out = { t: [], mv: [], temp: [], avg: [], liveFrom: live.length ? live[0].t : null };
    const cut = live.length ? live[0].t : Infinity;
    if (stored) for (let i = 0; i < stored.t.length; i++) if (stored.t[i] < cut) { out.t.push(stored.t[i]); out.mv.push(stored.mv[i]); out.temp.push(stored.temp[i]); out.avg.push(stored.avg[i]); }
    for (const s of live) { out.t.push(s.t); out.mv.push(s.mv[n - 1]); out.temp.push(null); out.avg.push(Math.round((s.mv.reduce((a, b) => a + b, 0) / s.mv.length) * 10) / 10); }
    return out;
  }, [stored, live, n, live.length]);
  const vals = P.mv.filter((v) => v != null);
  const rate = block.trend?.rate?.[n - 1];
  const Item = ({ l, children, sub }) => <div style={{ minWidth: 112 }}><div className="muted" style={{ fontSize: 11.5 }}>{l}</div>
    <div style={{ fontSize: 19, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{children}</div>{sub && <div className="muted" style={{ fontSize: 11.5 }}>{sub}</div>}</div>;
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 300, background: "rgba(0,0,0,.55)", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "6vh 16px", overflow: "auto" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: "min(980px, 100%)", background: "var(--panel, var(--bg))", color: "var(--fg)", border: "1px solid var(--border)", borderRadius: 14, padding: "14px 18px", boxShadow: "0 12px 40px rgba(0,0,0,.5)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <b style={{ fontSize: 18 }}>Článek #{n}</b>
          <span className="muted">{block.block_idx ? `B${block.block_idx}` : block.name} · box {Math.ceil(n / per)} · pozice {((n - 1) % per) + 1}</span>
          <button className="btn" onClick={onClose} style={{ marginLeft: "auto", fontWeight: 700 }}>✕ Zavřít (Esc)</button>
        </div>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", margin: "10px 0" }}>
          <Item l="Napětí teď" sub={`${mv - c.median >= 0 ? "+" : ""}${cs(mv - c.median, 0)} mV od mediánu`}><span style={{ color: CELL }}>{cs(mv / 1000, 3)} V</span></Item>
          <Item l="Pořadí v bloku" sub="1 = nejvyšší napětí">{rank}. z {all.length}</Item>
          <Item l="Teplota" sub="obnova 1× za minutu">{temps[n - 1] != null ? `${cs(temps[n - 1] / 10, 1)} °C` : "—"}</Item>
          <Item l="Trend" sub={block.trend ? `za ${block.trend.samples} snímků` : "po několika snímcích"}>{rate == null ? "—" : `${rate > 0 ? "+" : ""}${cs(rate, 2)} mV/min`}</Item>
          <Item l="V zobrazeném období" sub={`${vals.length} vzorků`}>{vals.length ? `${cs(Math.min(...vals) / 1000, 3)} – ${cs(Math.max(...vals) / 1000, 3)} V` : "—"}</Item>
          {energy?.in?.length > 0 && <Item l="Energie při balancování" sub={energy.in[n - 1] > 0.5 ? `poměr ${cs((energy.out[n - 1] / energy.in[n - 1]) * 100, 2)} %` : ""}>▲ {cs(energy.in[n - 1], 3)} · ▼ {cs(energy.out[n - 1], 3)} Wh</Item>}
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
          <span className="muted" style={{ fontSize: 12.5 }}>Období:</span>
          {RANGES.map(([h, lab]) => <button key={h} className="btn" onClick={() => setHours(h)} style={{ padding: "3px 11px", borderRadius: 999, fontWeight: hours === h ? 800 : 400, background: hours === h ? "#2a78d6" : undefined, color: hours === h ? "#fff" : undefined }}>{lab}</button>)}
        </div>
        {err ? <div style={{ color: "var(--red)", fontSize: 13 }}>⚠ {err}</div> : <Chart P={P} />}
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
          Zeleně podbarvený úsek = živá data po 5 s {live.length ? `(od ${new Date(live[0].t).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}, jen po dobu otevřeného okna nebo balancování)` : "(zatím žádná)"}.
          Starší část je z uložené historie: 1× za 5 minut, při testu baterie a balancování 1× za minutu.
        </div>
      </div>
    </div>);
}
