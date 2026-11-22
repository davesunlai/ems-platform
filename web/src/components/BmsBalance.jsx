import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import CursorBox, { CURSOR_LINE } from "./CursorBox";

// ⚖ Balancování bloku podle článků z BMS: ovládání, živý graf (zoom kolečkem, posun tažením, krok šipkami),
// pravítko 3,1–3,6 V se seřazenými články a historie s reportem. Řídí server (ems/bms/balance.py), tady se jen zobrazuje.
const HI = "#e0602c", LO = "#3987e5";                    // nejvyšší / nejnižší článek (ověřená dvojice pro světlý i tmavý vzhled)
const PH = { charge: { name: "Nabíjení", c: LO, icon: "▲" }, wait: { name: "Čekání na návrat", c: "#8a94a3", icon: "●" },
             discharge: { name: "Vybíjení", c: HI, icon: "▼" } };
const FIELDS = [
  ["delta_stop_v", "Mez rozpětí — stop nabíjení", "V", 0.001, "Nabíjení se zastaví, jakmile rozdíl mezi nejvyšším a nejnižším článkem dosáhne této hodnoty."],
  ["delta_resume_v", "Mez návratu", "V", 0.001, "Po zastavení se čeká, dokud rozdíl neklesne pod tuto hodnotu. Čas, který to trvá, je „doba návratu“."],
  ["delta_final_v", "Finální rozpětí (hotovo)", "V", 0.001, "Balancování skončí, když proběhne celý cyklus, ve kterém rozdíl tuto hodnotu ani jednou nepřekročil."],
  ["chg_ratio", "Poměr nabíjení (další cyklus)", "×", 0.05, "Nabíjecí výkon dalšího cyklu = tento poměr × nabíjecí výkon právě běžícího cyklu. 0,5 = každý cyklus poloviční."],
  ["dis_p_ratio", "Poměr vybíjecího výkonu", "×", 0.05, "Vybíjecí výkon = tento poměr × nabíjecí výkon téhož cyklu. 0,1 při nabíjení 10 kW = vybíjení 1 kW. 0 = nevybíjet."],
  ["dis_t_ratio", "Poměr doby vybíjení", "×", 0.05, "Doba vybíjení = tento poměr × doba nabíjení téhož cyklu. 0 = nevybíjet."],
  ["p_max_kw", "Plný výkon", "kW", 0.5, "Výkon prvního cyklu a nejvyšší výkon dalších cyklů. Hlavní jistič se hlídá zvlášť."],
  ["p_min_kw", "Minimální výkon", "kW", 0.1, "Když by další cyklus vyšel pod tento výkon, balancování skončí."],
  ["max_wait_min", "Nejdelší čekání", "min", 5, "Když se rozdíl do této doby pod mez návratu nevrátí, pokračuje se a doba návratu se bere jako tato."],
  ["cell_vtop", "Strop článku", "V", 0.01, "Nabíjení se zastaví i tehdy, když nejvyšší článek dosáhne této hodnoty (nejvýš 3,60 V)."],
  ["p_idle_kw", "Výkon při čekání", "kW", 0.05, "Při čekání měnič drží nucené nabíjení tímto malým výkonem, aby baterie nekryla dům."],
  ["max_hours", "Nejdelší běh", "h", 1, "Pojistka: po této době balancování skončí."],
];
// Logika 2 „vmax“: napětí nejvyššího článku, body podle SoC.
const FIELDS_V = [
  ["p_in_kw", "Vstupní výkon", "kW", 0.5, "Výkon, kterým začíná nabíjení každého bodu. Hlavní jistič se hlídá zvlášť."],
  ["chg_ratio", "Poměr následujícího nabíjecího výkonu", "×", 0.05, "Když se nejvyšší článek přiblíží ke stropu bodu (strop − hystereze), výkon se sníží na tento poměr. Opakuje se až k minimu bodu."],
  ["dis_p_ratio", "Poměr vybíjecího výkonu", "×", 0.05, "Vybíjecí výkon = tento poměr × poslední nabíjecí výkon. 0 = nevybíjet."],
  ["settle_s", "Prodleva mezi sníženími", "s", 5, "Po snížení výkonu se čeká tuto dobu, než smí přijít další snížení (měnič a články reagují se zpožděním)."],
  ["cell_vtop", "Strop článku (pojistka)", "V", 0.01, "Nabíjení skončí vždy, když nejvyšší článek dosáhne této hodnoty (nejvýš 3,60 V)."],
  ["max_hours", "Nejdelší běh", "h", 1, "Pojistka: po této době balancování skončí."],
];
const POINT_COLS = [
  ["soc", "do SoC %", 1, "Bod platí, dokud SoC nedosáhne této hodnoty (a neodjede se minimální počet cyklů)."],
  ["u_max", "strop článku V", 0.01, "Nejvyšší napětí nejvyššího článku v tomto bodě."],
  ["cycles", "min. cyklů", 1, "Nejmenší počet cyklů v bodě. Na další bod se jde, až je odjeto tolik cyklů A SoC dosáhlo hodnoty bodu."],
  ["hyst", "hystereze V", 0.005, "Výkon se začne snižovat při (strop − hystereze). Znaménko minus se ignoruje."],
  ["dis_t_ratio", "poměr doby vybíjení", 0.05, "Doba vybíjení = tento poměr × doba posledního schodu nabíjení."],
  ["p_min_kw", "min. výkon kW", 0.1, "Pod tuto hodnotu se nabíjecí výkon v bodě nesnižuje."],
];
const MODES = { vmax: "Napětí nejvyššího článku (body podle SoC)", delta: "Rozpětí článků (max − min)" };

const cs = (v, d = 0) => (v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toLocaleString("cs-CZ", { minimumFractionDigits: d, maximumFractionDigits: d }));
const dur = (s) => { if (s == null) return "—"; s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h} h ${String(m).padStart(2, "0")} min` : m ? `${m} min ${String(x).padStart(2, "0")} s` : `${x} s`; };
const clock = (ms, sec = true) => new Date(ms).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit", ...(sec ? { second: "2-digit" } : {}) });
const EMPTY = () => ({ t: [], phase: [], cycle: [], p_set: [], p_bat: [], vmax: [], vmin: [], vavg: [], delta: [], nmax: [], nmin: [], soc: [], ulim: [] });
const append = (a, b) => { const o = {}; for (const k of Object.keys(EMPTY())) o[k] = [...(a[k] || []), ...(b[k] || [])]; return o; };
const STEPS = [5e3, 1e4, 3e4, 6e4, 12e4, 3e5, 6e5, 9e5, 18e5, 36e5, 72e5, 144e5];

function useWidth(ref) {
  const [w, setW] = useState(900);
  useEffect(() => {
    if (!ref.current) return undefined;
    const ro = new ResizeObserver((e) => setW(Math.max(320, Math.round(e[0].contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

/** Graf průběhu: tři panely nad společnou časovou osou (napětí článků · rozpětí · výkon), pruhy = kroky cyklu. */
const changeText = (ch) => Object.entries(ch.changed || {}).map(([k, [o, nv]]) => {
  const f = FIELDS.find((x) => x[0] === k) || [k, k, ""]; const d = f[2] === "V" ? 3 : 2;
  return `${f[1]} ${cs(o, d)} → ${cs(nv, d)} ${f[2]}`; }).join(", ");

function BalanceChart({ S, params, live, changes = [] }) {
  const box = useRef(null);
  const W = useWidth(box);
  const n = S.t.length;
  const [view, setView] = useState(null);                 // [od, do] v ms; null = celý průběh a sleduje konec
  const [cur, setCur] = useState(null);                   // index vzorku pod kurzorem
  const [pos, setPos] = useState(null);
  const drag = useRef(null);
  const t0 = n ? S.t[0] : 0, t1 = n ? S.t[n - 1] : 1;
  const a = view ? view[0] : t0, b = view ? view[1] : Math.max(t1, t0 + 6e4);
  const padL = 58, padR = 88, plotW = Math.max(100, W - padL - padR);
  const X = (t) => padL + ((t - a) / (b - a)) * plotW;
  const tAt = (px) => a + ((px - padL) / plotW) * (b - a);
  const idxAt = useCallback((t) => { let lo = 0, hi = n - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (S.t[m] < t) lo = m + 1; else hi = m; }
    return lo > 0 && Math.abs(S.t[lo - 1] - t) < Math.abs(S.t[lo] - t) ? lo - 1 : lo; }, [S, n]);

  useEffect(() => {                                       // kolečko = zoom kolem kurzoru (nepasivní posluchač kvůli preventDefault)
    const el = box.current;
    if (!el) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const tc = tAt(Math.max(padL, Math.min(padL + plotW, e.clientX - r.left)));
      const k = e.deltaY > 0 ? 1.25 : 0.8;
      let na = tc - (tc - a) * k, nb = tc + (b - tc) * k;
      if (nb - na < 3e4) { const c = (na + nb) / 2; na = c - 15e3; nb = c + 15e3; }
      if (na <= t0 && nb >= t1) return setView(null);
      setView([Math.max(t0 - 6e4, na), Math.min(t1 + 6e4, nb)]);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });
  if (!n) return <div ref={box} className="muted" style={{ fontSize: 13, padding: "26px 0" }}>Graf se začne kreslit s prvním vzorkem (do 10 s od spuštění).</div>;

  let i0 = idxAt(a), i1 = idxAt(b);
  i0 = Math.max(0, i0 - 1); i1 = Math.min(n - 1, i1 + 1);
  const stride = Math.max(1, Math.ceil((i1 - i0 + 1) / 1400));
  const ix = []; for (let i = i0; i <= i1; i += stride) ix.push(i); if (ix[ix.length - 1] !== i1) ix.push(i1);
  const range = (keys, pad, floor0) => { let lo = Infinity, hi = -Infinity;
    for (const i of ix) for (const k of keys) { const v = S[k][i]; if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } }
    if (!Number.isFinite(lo)) { lo = 0; hi = 1; } if (floor0) lo = Math.min(0, lo);
    const p = Math.max((hi - lo) * 0.12, pad); return [lo - (floor0 && lo === 0 ? 0 : p), hi + p]; };
  const hasLim = (S.ulim || []).some((v) => v != null);       // logika „vmax“: strop bodu jako schodová čára místo mezí rozpětí
  const panels = [
    { key: "v", title: "Napětí článků (V)", h: 150, r: range(hasLim ? ["vmax", "vmin", "ulim"] : ["vmax", "vmin"], 4), f: (v) => cs(v / 1000, 3),
      lines: [{ k: "vmax", c: HI, label: "max" }, { k: "vmin", c: LO, label: "min" }, { k: "vavg", c: "var(--fg)", label: "průměr", dash: "5 4" },
              ...(hasLim ? [{ k: "ulim", c: "var(--green)", label: "strop bodu", step: true, dash: "7 3" }] : [])] },
    { key: "d", title: "Rozpětí max − min (mV)", h: 105, r: [0, Math.max(range(["delta"], 2, true)[1], (params?.delta_stop_v || 0) * 1000 * 1.15)], f: (v) => cs(v, 0),
      lines: [{ k: "delta", c: "var(--fg)", label: "rozpětí" }],
      marks: hasLim ? [] : [[params?.delta_stop_v, "stop", HI], [params?.delta_final_v, "finál", "var(--green)"], [params?.delta_resume_v, "návrat", LO]] },
    { key: "p", title: "Výkon baterie (kW, + nabíjení)", h: 105, r: range(["p_set", "p_bat"], 0.3, true), f: (v) => cs(v, 1),
      lines: [{ k: "p_set", c: "var(--fg)", label: "povel", step: true }, { k: "p_bat", c: "var(--green)", label: "změřeno" }] },
    { key: "s", title: "SoC podle BMS (%)", h: 80, r: range(["soc"], 1.5), f: (v) => cs(v, 0),
      lines: [{ k: "soc", c: "var(--fg)", label: "SoC" }] },
  ];
  const GAP = 26, TOP = 40;
  let y = TOP; for (const p of panels) { p.y = y; y += p.h + GAP; }
  const H = y - GAP + 26;
  const Yp = (p, v) => p.y + p.h * (1 - (v - p.r[0]) / (p.r[1] - p.r[0] || 1));
  const path = (p, l) => { let d = "", pen = false, py = 0;
    for (const i of ix) { const v = S[l.k][i]; if (v == null) { pen = false; continue; } const x = X(S.t[i]), yy = Yp(p, v);
      d += pen ? (l.step ? `H${x.toFixed(1)}V${yy.toFixed(1)}` : `L${x.toFixed(1)} ${yy.toFixed(1)}`) : `M${x.toFixed(1)} ${yy.toFixed(1)}`; pen = true; py = yy; }
    return [d, py]; };
  const hasPh = S.phase.some((x) => x != null);
  const bands = []; if (hasPh) { let s = i0; for (let i = i0 + 1; i <= i1 + 1; i++) if (i > i1 || S.phase[i] !== S.phase[s] || S.cycle[i] !== S.cycle[s]) {
    bands.push({ ph: S.phase[s], cy: S.cycle[s], x0: X(S.t[s]), x1: X(S.t[Math.min(i, i1)]) }); s = i; } }
  const step = STEPS.find((s) => (b - a) / s <= Math.max(4, plotW / 95)) || STEPS[STEPS.length - 1];
  const ticks = []; for (let t = Math.ceil(a / step) * step; t <= b; t += step) ticks.push(t);
  const clipX = (x) => Math.max(padL, Math.min(padL + plotW, x));
  const marks = changes.map((ch) => ({ ...ch, ms: new Date(ch.t).getTime() })).filter((ch) => ch.ms >= a && ch.ms <= b);
  const nearTol = Math.max(5000, ((b - a) / plotW) * 7);          // změna „pod kurzorem“ = do 7 px
  const move = (e) => { const r = box.current.getBoundingClientRect(); const px = e.clientX - r.left;
    if (drag.current) { const dt = ((drag.current.x - e.clientX) / plotW) * (drag.current.b - drag.current.a);
      return setView([drag.current.a + dt, drag.current.b + dt]); }
    setCur(idxAt(tAt(clipX(px)))); setPos({ x: px, y: e.clientY - r.top, w: r.width, h: r.height }); };
  const key = (e) => { if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return; e.preventDefault();
    const i = Math.max(0, Math.min(n - 1, (cur ?? n - 1) + (e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 12 : 1))); setCur(i);
    setPos((p) => ({ x: X(S.t[i]), y: p?.y ?? 60, w: W, h: H }));
    if (S.t[i] < a || S.t[i] > b) { const half = (b - a) / 2; setView([S.t[i] - half, S.t[i] + half]); } };
  const c = cur != null && cur < n ? cur : null;
  return (
    <div ref={box} tabIndex={0} onKeyDown={key} onMouseMove={move} onMouseLeave={() => { setCur(null); setPos(null); drag.current = null; }}
         onMouseDown={(e) => { drag.current = { x: e.clientX, a, b }; }} onMouseUp={() => { drag.current = null; }} onDoubleClick={() => setView(null)}
         style={{ position: "relative", outline: "none", cursor: drag.current ? "grabbing" : "crosshair", userSelect: "none" }}>
      <svg width={W} height={H} style={{ display: "block" }}>
        <defs><clipPath id="balclip"><rect x={padL} y={0} width={plotW} height={H} /></clipPath></defs>
        <g clipPath="url(#balclip)">
          {bands.map((bd, i) => bd.x1 > bd.x0 && <g key={i}>
            <rect x={bd.x0} y={TOP} width={bd.x1 - bd.x0} height={H - TOP - 26} fill={(PH[bd.ph] || PH.wait).c} opacity={bd.ph === "wait" ? 0.07 : 0.11} />
            <rect x={bd.x0} y={6} width={Math.max(0, bd.x1 - bd.x0 - 2)} height={10} rx={3} fill={(PH[bd.ph] || PH.wait).c} opacity={0.85} />
            {bd.x1 - bd.x0 > 46 && <text x={(bd.x0 + bd.x1) / 2} y={14.5} textAnchor="middle" fontSize={9.5} fontWeight={700} fill="#fff">{(PH[bd.ph] || PH.wait).icon} {bd.cy}</text>}
          </g>)}
        </g>
        {panels.map((p) => <g key={p.key}>
          <text x={padL} y={p.y - 6} fontSize={11.5} fill="var(--muted)">{p.title}</text>
          {[0, 0.5, 1].map((q) => { const v = p.r[0] + (p.r[1] - p.r[0]) * q; return <g key={q}>
            <line x1={padL} x2={padL + plotW} y1={Yp(p, v)} y2={Yp(p, v)} stroke="var(--border)" strokeWidth={1} />
            <text x={padL - 6} y={Yp(p, v) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{p.f(v)}</text></g>; })}
          <g clipPath="url(#balclip)">
            {p.key === "v" && (() => { const up = ix.map((i) => `${X(S.t[i]).toFixed(1)},${Yp(p, S.vmax[i]).toFixed(1)}`);
              const dn = [...ix].reverse().map((i) => `${X(S.t[i]).toFixed(1)},${Yp(p, S.vmin[i]).toFixed(1)}`);
              return <polygon points={[...up, ...dn].join(" ")} fill="var(--fg)" opacity={0.06} />; })()}
            {(p.marks || []).map(([v, lab, col]) => v != null && v * 1000 <= p.r[1] && <g key={lab}>
              <line x1={padL} x2={padL + plotW} y1={Yp(p, v * 1000)} y2={Yp(p, v * 1000)} stroke={col} strokeWidth={1.2} strokeDasharray="6 4" /></g>)}
            {p.lines.map((l) => <path key={l.k} d={path(p, l)[0]} fill="none" stroke={l.c} strokeWidth={2} strokeDasharray={l.dash} strokeLinejoin="round" />)}
          </g>
          {(p.marks || []).map(([v, lab]) => v != null && v * 1000 <= p.r[1] &&
            <text key={lab} x={padL + plotW + 6} y={Yp(p, v * 1000) + 4} fontSize={11} fill="var(--muted)">{lab} {cs(v * 1000, 0)}</text>)}
          {!(p.marks && p.marks.length) && (() => { const ys = p.lines.map((l) => { const [d, yy] = path(p, l); return { l, y: yy, d }; }).filter((x) => x.d).sort((m, q) => m.y - q.y);
            for (let i = 1; i < ys.length; i++) if (ys[i].y - ys[i - 1].y < 13) ys[i].y = ys[i - 1].y + 13;
            return ys.map(({ l, y: yy }) => <g key={l.k}><circle cx={padL + plotW + 7} cy={yy} r={4} fill={l.c} /><text x={padL + plotW + 15} y={yy + 4} fontSize={11.5} fill="var(--fg)">{l.label}</text></g>); })()}
        </g>)}
        {marks.map((ch, i) => <g key={`ch${i}`}>
          <title>{`${clock(ch.ms)} · změna parametrů${ch.by ? ` (${ch.by})` : ""}: ${changeText(ch)}`}</title>
          <line x1={X(ch.ms)} x2={X(ch.ms)} y1={TOP - 12} y2={H - 26} stroke="var(--fg)" strokeWidth={1.4} strokeDasharray="2 4" />
          <circle cx={X(ch.ms)} cy={TOP - 14} r={8} fill="var(--fg)" />
          <text x={X(ch.ms)} y={TOP - 10} textAnchor="middle" fontSize={11} fontWeight={800} fill="var(--panel, #fff)">✎</text>
        </g>)}
        {ticks.map((t) => <g key={t}><line x1={X(t)} x2={X(t)} y1={H - 26} y2={H - 21} stroke="var(--muted)" />
          <text x={X(t)} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--muted)">{clock(t, step < 6e4)}</text></g>)}
        {c != null && S.t[c] >= a && S.t[c] <= b && <g>
          <line x1={X(S.t[c])} x2={X(S.t[c])} y1={TOP} y2={H - 26} {...CURSOR_LINE} />
          {panels.flatMap((p) => p.lines.map((l) => S[l.k][c] != null &&
            <circle key={p.key + l.k} cx={X(S.t[c])} cy={Yp(p, S[l.k][c])} r={4.5} fill={l.c} stroke="var(--panel)" strokeWidth={2} />))}
        </g>}
      </svg>
      {c != null && <CursorBox pos={pos} width={236} height={200}>
        <b>{clock(S.t[c])}</b>{S.phase[c] != null && <> · {(PH[S.phase[c]] || PH.wait).icon} {(PH[S.phase[c]] || PH.wait).name}, cyklus {S.cycle[c]}</>}
        <div><span style={{ color: HI }}>●</span> max {cs(S.vmax[c] / 1000, 3)} V <span className="muted">(č. {S.nmax[c]})</span></div>
        <div><span style={{ color: LO }}>●</span> min {cs(S.vmin[c] / 1000, 3)} V <span className="muted">(č. {S.nmin[c]})</span></div>
        <div>průměr {cs(S.vavg[c] / 1000, 3)} V · rozpětí <b>{cs(S.delta[c])} mV</b></div>
        {S.ulim?.[c] != null && <div><span style={{ color: "var(--green)" }}>●</span> strop bodu {cs(S.ulim[c] / 1000, 3)} V <span className="muted">(do stropu {cs(S.ulim[c] - S.vmax[c])} mV)</span></div>}
        <div>{S.p_set[c] != null ? `povel ${cs(S.p_set[c], 1)} kW · ` : ""}změřeno {cs(S.p_bat[c], 2)} kW</div>
        <div className="muted">SoC {cs(S.soc[c], 0)} % · od startu {dur((S.t[c] - t0) / 1000)}</div>
        {marks.filter((ch) => Math.abs(ch.ms - S.t[c]) <= nearTol).map((ch, i) =>
          <div key={i} style={{ marginTop: 4, paddingTop: 4, borderTop: "1px solid var(--border)", whiteSpace: "normal", maxWidth: 300 }}>
            <b>✎ {clock(ch.ms)} změna parametrů</b>{ch.by ? ` (${ch.by})` : ""}<br />{changeText(ch)}</div>)}
      </CursorBox>}
      <div className="muted" style={{ fontSize: 11.5, display: "flex", gap: 14, flexWrap: "wrap", marginTop: 2 }}>
        {hasPh && Object.entries(PH).map(([k, v]) => <span key={k}><i style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: v.c, marginRight: 5, verticalAlign: "-1px" }} />{v.icon} {v.name}</span>)}
        {hasPh && <span>číslo v pruhu = cyklus</span>}
        {changes.length > 0 && <span>✎ = změna parametrů ({changes.length}×)</span>}
        <span style={{ marginLeft: "auto" }}>kolečko = zoom · tažení = posun · ← → = krok po vzorku (Shift = po minutě) · dvojklik = celý průběh
          {view ? <> · <a href="#" onClick={(e) => { e.preventDefault(); setView(null); }}>{live ? "▶ sledovat živě" : "zobrazit vše"}</a></> : live ? " · sleduje živě" : ""}</span>
      </div>
    </div>);
}

/** Pravítko 3,1–3,6 V a pod ním všechny články seřazené od nejvyššího; pozice značky = napětí článku. */
function CellRuler({ cells, params, energy, limit, hover, onHover, onPick }) {
  const wrap = useRef(null);
  const hasE = !!(energy?.in?.length);
  const V0 = 3100, V1 = 3600, ROW = 19, LAB = hasE ? 422 : 172;
  const ratioOf = (n) => { const i = energy.in[n - 1], o = energy.out[n - 1]; return i > 0.5 ? (o / i) * 100 : null; };
  const list = useMemo(() => { const out = []; let n = 0;
    for (const m of cells.modules) m.mv.forEach((mv, i) => out.push({ n: ++n, mod: m.idx, pos: i + 1, mv }));
    const order = [...out].sort((p, q) => q.mv - p.mv || p.n - q.n); order.forEach((c, r) => { c.rank = r; }); return out; }, [cells]);
  const pct = (mv) => `${Math.max(0, Math.min(100, ((mv - V0) / (V1 - V0)) * 100))}%`;
  const avg = list.reduce((s, c) => s + c.mv, 0) / (list.length || 1);
  const stop = (params?.delta_stop_v || 0) * 1000;
  const marks = []; for (let v = V0; v <= V1; v += 50) marks.push(v);
  const hovRank = hover && hover.src !== "ruler" ? list.find((x) => x.n === hover.n)?.rank : null;
  useEffect(() => {                                   // najetí v tabulce → seznam se posune na řádek článku
    if (hovRank == null || !wrap.current) return;
    const el = wrap.current, y = hovRank * ROW;
    if (y < el.scrollTop + 40 || y > el.scrollTop + el.clientHeight - 60) el.scrollTo({ top: Math.max(0, y - el.clientHeight / 2), behavior: "smooth" });
  }, [hovRank]);
  return (
    <div ref={wrap} style={{ border: "1px solid var(--border)", borderRadius: 10, overflow: "auto", maxHeight: 560, position: "relative" }}>
      <div style={{ position: "sticky", top: 0, zIndex: 3, background: "var(--panel, var(--bg))", borderBottom: "1px solid var(--border)", padding: "6px 14px 4px 0", display: "flex" }}>
        <div style={{ width: LAB, flex: "none", fontSize: 11.5, paddingLeft: 10 }} className="muted">článek · box/pozice · mV{hasE && <span title="Energie do článku (nabíjení) a z článku (vybíjení) od začátku balancování; poměr = z článku ÷ do článku. Články jsou v sérii, proud je stejný — rozdíly dělá jen napětí článku."> · ▲ do Wh · ▼ z Wh · poměr</span>}</div>
        <div style={{ position: "relative", flex: 1, height: 30 }}>
          {marks.map((v) => <div key={v} style={{ position: "absolute", left: pct(v), top: 0, transform: "translateX(-50%)", textAlign: "center", fontSize: v % 100 ? 10.5 : 12, fontWeight: v % 100 ? 400 : 700 }}>
            <div>{v % 100 ? "" : cs(v / 1000, 1)}{v % 100 ? cs(v / 1000, 2) : ""}</div>
            <div style={{ width: 1, height: v % 100 ? 5 : 9, background: "var(--fg)", margin: "1px auto 0", opacity: 0.7 }} /></div>)}
        </div>
      </div>
      <div style={{ position: "relative", height: list.length * ROW + 6, marginRight: 14 }}>
        <div style={{ position: "absolute", left: LAB, right: 0, top: 0, bottom: 0, pointerEvents: "none" }}>
          {limit && [[limit.ulim, "solid"], [limit.thr, "dashed"]].map(([v, st2]) =>
            <div key={st2} className="bal-move" title={st2 === "solid" ? "strop bodu" : "strop − hystereze (od této hodnoty se snižuje výkon)"}
                 style={{ position: "absolute", top: 0, bottom: 0, left: pct(v), width: 0, borderLeft: `2px ${st2} var(--green)` }} />)}
          {!limit && stop > 0 && <div className="bal-move" style={{ position: "absolute", top: 0, bottom: 0, left: pct(cells.min), width: `${(stop / (V1 - V0)) * 100}%`, background: "var(--green)", opacity: 0.09 }}
                            title="Pásmo meze rozpětí od nejnižšího článku" />}
          {[[cells.max, HI], [cells.min, LO], [avg, "var(--fg)"]].map(([v, col], i) =>
            <div key={i} className="bal-move" style={{ position: "absolute", top: 0, bottom: 0, left: pct(v), width: 0, borderLeft: `1.5px ${i === 2 ? "dashed" : "solid"} ${col}`, opacity: 0.55 }} />)}
        </div>
        {list.map((c) => { const top = c.rank === 0, bot = c.rank === list.length - 1; const col = c.mv >= avg ? HI : LO;
          return (
            <div key={c.n} className="bal-row" title="klik = průběh článku"
                 onMouseEnter={onHover ? () => onHover({ n: c.n, src: "ruler" }) : undefined} onMouseLeave={onHover ? () => onHover(null) : undefined} onClick={onPick ? () => onPick(c.n) : undefined}
                 style={{ position: "absolute", left: 0, right: 0, top: c.rank * ROW + 3, height: ROW, display: "flex", alignItems: "center", cursor: onPick ? "pointer" : undefined,
                          background: hover?.n === c.n ? "color-mix(in srgb, var(--fg) 16%, transparent)" : undefined, boxShadow: hover?.n === c.n ? "inset 3px 0 0 var(--fg)" : undefined }}>
              <div style={{ width: LAB, flex: "none", paddingLeft: 10, fontSize: 12, fontVariantNumeric: "tabular-nums", fontWeight: top || bot ? 800 : 400, whiteSpace: "nowrap" }}>
                <span style={{ display: "inline-block", width: 40 }}>#{c.n}</span>
                <span style={{ display: "inline-block", width: 50, fontSize: 12, color: "var(--muted)" }}>{c.mod}/{c.pos}</span>
                <span style={{ display: "inline-block", width: 46 }}>{cs(c.mv)}</span>
                {hasE && <span style={{ fontWeight: 400 }}>
                  <span style={{ display: "inline-block", width: 84, textAlign: "right", color: LO }}>▲ {cs(energy.in[c.n - 1], 3)}</span>
                  <span style={{ display: "inline-block", width: 84, textAlign: "right", color: HI }}>▼ {cs(energy.out[c.n - 1], 3)}</span>
                  <span style={{ display: "inline-block", width: 72, textAlign: "right", fontWeight: 700 }}>{ratioOf(c.n) == null ? "—" : `${cs(ratioOf(c.n), 2)} %`}</span>
                </span>}
              </div>
              <div style={{ position: "relative", flex: 1, height: "100%" }}>
                <div style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 1, background: "var(--border)" }} />
                <div className="bal-move" style={{ position: "absolute", top: "50%", left: pct(c.mv), width: top || bot ? 13 : 9, height: top || bot ? 13 : 9, borderRadius: 7,
                              transform: "translate(-50%,-50%)", background: col, boxShadow: "0 0 0 2px var(--panel, var(--bg))" }} />
              </div>
            </div>); })}
      </div>
    </div>);
}

function Stat({ label, children, sub, color }) {
  return (<div style={{ minWidth: 118 }}>
    <div className="muted" style={{ fontSize: 11.5 }}>{label}</div>
    <div style={{ fontSize: 21, fontWeight: 700, color: color || "var(--fg)", fontVariantNumeric: "tabular-nums", lineHeight: 1.25 }}>{children}</div>
    {sub && <div className="muted" style={{ fontSize: 11.5 }}>{sub}</div>}
  </div>);
}

/** Poměr energie z článku ÷ do článku pro každý článek (řádek = box), podbarvení podle odchylky od průměru. */
function CellEnergy({ ce }) {
  const per = ce.per_module || 15, rows = [];
  for (let i = 0; i < ce.ratio_pct.length; i += per) rows.push(ce.ratio_pct.slice(i, i + per).map((r, k) => ({ r, n: i + k + 1 })));
  const vals = ce.ratio_pct.filter((x) => x != null), avg = ce.ratio_avg ?? 0;
  const span = Math.max(0.05, ...vals.map((x) => Math.abs(x - avg)));
  const bg = (r) => { if (r == null) return "transparent"; const a = Math.abs(r - avg) / span; return a < 0.25 ? "transparent" : `color-mix(in srgb, ${r < avg ? HI : LO} ${Math.round(18 + a * 40)}%, transparent)`; };
  return (<div style={{ marginTop: 10 }}>
    <div style={{ fontWeight: 700, marginBottom: 2 }}>Energie článků: poměr z článku ÷ do článku (%)</div>
    <div className="muted" style={{ marginBottom: 6 }}>Průměr {cs(ce.ratio_avg, 2)} % · nejnižší {ce.ratio_min ? `${cs(ce.ratio_min[0], 2)} % (č. ${ce.ratio_min[1]})` : "—"} · nejvyšší {ce.ratio_max ? `${cs(ce.ratio_max[0], 2)} % (č. ${ce.ratio_max[1]})` : "—"}.
      Články jsou v sérii, teče jimi stejný proud; rozdíl v poměru je dán jen napětím článku při nabíjení a vybíjení. <span style={{ color: HI }}>■</span> pod průměrem (článek se při nabíjení zvedá a při vybíjení propadá víc než ostatní), <span style={{ color: LO }}>■</span> nad průměrem. Najetím na buňku uvidíš Wh.</div>
    <div style={{ overflow: "auto" }}><table style={{ borderCollapse: "collapse", fontSize: 12, fontVariantNumeric: "tabular-nums" }}><tbody>
      {rows.map((row, m) => <tr key={m}><td className="muted" style={{ padding: "2px 8px 2px 0", whiteSpace: "nowrap" }}>box {m + 1}</td>
        {row.map((c) => <td key={c.n} title={`článek ${c.n}: do ${cs(ce.in_wh[c.n - 1], 3)} Wh, z ${cs(ce.out_wh[c.n - 1], 3)} Wh`}
                            style={{ padding: "2px 6px", textAlign: "right", background: bg(c.r), border: "1px solid var(--border)", fontWeight: c.n === ce.ratio_min?.[1] || c.n === ce.ratio_max?.[1] ? 800 : 400 }}>{c.r == null ? "—" : cs(c.r, 2)}</td>)}</tr>)}
    </tbody></table></div>
  </div>);
}

function Report({ run }) {
  const r = run.result || {}, cyc = run.state?.cycles || [], p = run.params || {};
  const isV = p.mode === "vmax";
  return (<div style={{ fontSize: 13 }}>
    <div style={{ display: "flex", gap: 22, flexWrap: "wrap", margin: "8px 0 10px" }}>
      <Stat label="Výsledek" color={run.status === "done" ? "var(--green)" : run.status === "aborted" ? "var(--red)" : undefined}>
        {{ done: "dokončeno", stopped: "zastaveno", aborted: "přerušeno", running: "běží" }[run.status] || run.status}</Stat>
      <Stat label="Trvání">{dur(r.duration_s)}</Stat>
      <Stat label="Cyklů">{cs(r.cycles ?? cyc.length)}</Stat>
      <Stat label="Rozpětí začátek → konec">{cs(r.delta_start_mv)} → {cs(r.delta_end_mv)} mV</Stat>
      <Stat label="Výkon první → poslední">{cs(r.p_first_kw, 1)} → {cs(r.p_last_kw, 1)} kW</Stat>
      <Stat label="Nabito / vybito">{cs(r.e_charged_kwh, 1)} / {cs(r.e_discharged_kwh, 1)} kWh</Stat>
      <Stat label="SoC">{cs(r.soc_start)} → {cs(r.soc_end)} %</Stat>
    </div>
    {r.reason && <div style={{ marginBottom: 8 }}><b>Důvod konce:</b> {r.reason}</div>}
    <div className="muted" style={{ marginBottom: 4 }}>Parametry {run.state?.params_log?.length ? `(na konci; během běhu změněny ${run.state.params_log.length}×)` : ""}</div>
    <div style={{ display: "flex", gap: "4px 18px", flexWrap: "wrap", marginBottom: 10 }}>
      <span>Logika: <b>{MODES[p.mode] || MODES.delta}</b></span>
      {(isV ? FIELDS_V : FIELDS).map(([k, lab, u]) => <span key={k}>{lab}: <b>{cs(p[k], u === "V" ? 3 : 2)} {u}</b></span>)}
    </div>
    {isV && <div style={{ marginBottom: 10 }}>{(p.points || []).map((pt, i) => <div key={i}>Bod {i + 1}: do <b>{cs(pt.soc)} %</b> SoC · strop <b>{cs(pt.u_max, 3)} V</b> · min. {pt.cycles} cyklů · hystereze {cs(pt.hyst, 3)} V · doba vybíjení × {cs(pt.dis_t_ratio, 2)} · min. výkon {cs(pt.p_min_kw, 2)} kW</div>)}</div>}
    {(run.state?.params_log || []).map((c, i) => <div key={i} className="muted">✎ {clock(new Date(c.t).getTime())} {c.by}: {Object.entries(c.changed).map(([k, [o, nv]]) =>
      (k === "points" ? "body upraveny" : `${([...FIELDS, ...FIELDS_V].find((f) => f[0] === k) || [k, k])[1]} ${cs(o, 3)} → ${cs(nv, 3)}`)).join(", ")}</div>)}
    {isV && cyc.length > 0 && <div style={{ overflow: "auto", marginTop: 8 }}><table className="tbl" style={{ fontSize: 12.5, borderCollapse: "collapse", minWidth: 720 }}>
      <thead><tr>{["cyklus", "bod", "schody výkonu kW", "doba nabíjení", "poslední schod", "článek při stopu", "strop bodu", "SoC %", "vybíjení kW", "doba vybíjení"].map((h) =>
        <th key={h} style={{ textAlign: "right", padding: "3px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600 }} className="muted">{h}</th>)}</tr></thead>
      <tbody>{cyc.map((c) => <tr key={c.n}>{[c.n, c.pt, (c.steps || [c.p_kw]).map((x) => cs(x, 2)).join(" → "), dur(c.t_charge_s), dur(c.t_last_s), `${cs(c.vmax_mv)} mV`, `${cs(c.u_max_mv)} mV`,
        cs(c.soc), cs(c.p_dis_kw, 2), dur(c.t_discharge_s)].map((v, i) =>
        <td key={i} style={{ textAlign: "right", padding: "3px 10px", borderBottom: "1px solid var(--border)", fontVariantNumeric: "tabular-nums" }}>{v}</td>)}</tr>)}</tbody>
    </table></div>}
    {!isV && cyc.length > 0 && <div style={{ overflow: "auto", marginTop: 8 }}><table className="tbl" style={{ fontSize: 12.5, borderCollapse: "collapse", minWidth: 640 }}>
      <thead><tr>{["cyklus", "nabíjení kW", "doba nabíjení", "zastaveno", "rozpětí při stopu", "doba návratu", "vybíjení kW", "doba vybíjení", "největší rozpětí", "další nabíjení kW"].map((h) =>
        <th key={h} style={{ textAlign: "right", padding: "3px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600 }} className="muted">{h}</th>)}</tr></thead>
      <tbody>{cyc.map((c) => <tr key={c.n}>{[c.n, cs(c.p_kw, 2), dur(c.t_charge_s), c.stop_by, `${cs(c.delta_stop_mv)} mV`,
        c.t_return_s == null ? "—" : `${dur(c.t_return_s)}${c.return_timeout ? " (limit)" : ""}`, cs(c.p_dis_kw ?? c.p_kw, 2), dur(c.t_discharge_s), c.delta_max_mv == null ? "—" : `${cs(c.delta_max_mv)} mV`, cs(c.p_next_kw, 2)].map((v, i) =>
        <td key={i} style={{ textAlign: "right", padding: "3px 10px", borderBottom: "1px solid var(--border)", fontVariantNumeric: "tabular-nums" }}>{v}</td>)}</tr>)}</tbody>
    </table></div>}
    {r.cell_energy?.ratio_pct?.length > 0 && <CellEnergy ce={r.cell_energy} />}
  </div>);
}

export default function BmsBalance({ block, open, setOpen, hover, onHover, onPick, localHist }) {
  const { has } = useAuth();
  const canCtl = has("control");
  const mid = block.module_id, c = block.cells;
  const [run, setRun] = useState(null);
  const [S, setS] = useState(EMPTY);
  const [form, setForm] = useState(null);                // parametry logiky „rozpětí“
  const [formV, setFormV] = useState(null);              // parametry logiky „napětí nejvyššího článku“
  const [mode, setMode] = useState("vmax");             // výchozí logika = napětí nejvyššího článku (body podle SoC), v1.13.3
  const [dirty, setDirty] = useState(false);
  const [hist, setHist] = useState([]);
  const [past, setPast] = useState(null);               // otevřený záznam z historie {run, S}
  const [msg, setMsg] = useState("");
  const last = useRef(0), rid = useRef(null), dirtyRef = useRef(false);
  dirtyRef.current = dirty;

  const loadHist = useCallback(() => api.balHistory(mid).then(setHist).catch(() => {}), [mid]);
  useEffect(() => { api.balDefaults(mid).then((d) => { setForm((f) => f || d.params); setFormV((f) => f || d.params_vmax); }).catch(() => {}); loadHist(); }, [mid, loadHist]);
  useEffect(() => {
    let dead = false;
    const tick = async () => {
      try {
        const act = await api.balActive(mid);
        const id = act?.id ?? rid.current;
        if (!id) return;
        if (rid.current !== id) { rid.current = id; last.current = 0; setS(EMPTY()); }
        const d = await api.balRun(id, last.current || null);
        if (dead) return;
        if (d.samples.t.length) { last.current = d.samples.t[d.samples.t.length - 1]; setS((s) => append(s, d.samples)); }
        setRun(d.run);
        if (d.run.status === "running") { setOpen(true); const m = d.run.params.mode === "vmax" ? "vmax" : "delta"; setMode(m);
          if (!dirtyRef.current) (m === "vmax" ? setFormV : setForm)(d.run.params); }
        else if (act == null) { rid.current = null; loadHist(); }
      } catch { /* další pokus za 5 s */ }
    };
    tick();
    const h = setInterval(tick, 5000);
    return () => { dead = true; clearInterval(h); };
  }, [mid, setOpen, loadHist]);

  const running = run?.status === "running";
  const n1 = (v) => (v === "" || v == null ? null : Number(String(v).replace(",", ".")));
  const num = (o) => ({ ...Object.fromEntries(Object.entries(o || {}).filter(([k]) => k !== "mode" && k !== "points").map(([k, v]) => [k, n1(v)])), mode: "delta" });
  const numV = (o) => ({ ...Object.fromEntries(Object.entries(o || {}).filter(([k]) => k !== "mode" && k !== "points").map(([k, v]) => [k, n1(v)])), mode: "vmax",
    points: (o?.points || []).map((pt) => Object.fromEntries(Object.entries(pt).map(([k, v]) => [k, n1(v)]))) });
  const curForm = mode === "vmax" ? formV : form;
  const cur = mode === "vmax" ? numV(formV) : num(form);
  const setPoint = (i, k, v) => { setFormV({ ...formV, points: formV.points.map((pt, j) => (j === i ? { ...pt, [k]: v } : pt)) }); setDirty(true); };
  const act = async (fn, ok) => { setMsg(""); try { await fn(); if (ok) setMsg(ok); } catch (e) { setMsg(`⚠ ${e.message}`); } };
  const start = () => { if (!window.confirm(`Spustit balancování ${block.block_idx ? `B${block.block_idx}` : block.name}?\n\nTERA převezme řízení baterie: logika „${MODES[mode]}“, nabíjení ze sítě až ${cs(mode === "vmax" ? cur.p_in_kw : cur.p_max_kw, 1)} kW, baterie po dobu běhu nekryje dům, ve vybíjecím kroku jde energie do domu / sítě. Plánovač a pravidla jsou po dobu běhu pozastavené. Měnič řídí všechny zapnuté bloky zároveň.`)) return;
    act(async () => { const r = await api.balStart({ bms_module_id: mid, params: cur, confirmed: true }); rid.current = r.id; last.current = 0; setS(EMPTY()); setRun(r); setDirty(false); setPast(null); }); };
  const stop = () => window.confirm("Zastavit balancování a vrátit měnič do běžného režimu?") && act(async () => setRun(await api.balStop(run.id)), "Zastaveno, měnič se vrací do běžného režimu.");
  const apply = () => act(async () => { setRun(await api.balParams(run.id, cur)); setDirty(false); }, "Parametry změněny, platí od dalšího kroku.");
  const fix = () => act(async () => { await api.balSaveDefaults(mid, cur); }, "📌 Zafixováno jako výchozí pro příští balancování.");
  const openPast = (id) => act(async () => { const d = await api.balRun(id, null); setPast({ run: d.run, S: d.samples }); });

  if (!open) return null;
  const st0 = run?.status === "running" ? run.state : null;
  const p = running ? run.params : cur;
  const isV = p.mode === "vmax";
  const ptI = isV ? Math.min(Number(st0?.pt ?? 0), (p.points || []).length - 1) : 0;
  const pt = isV ? (p.points || [])[ptI] : null;
  const limit = pt && pt.u_max != null ? { ulim: pt.u_max * 1000, thr: (pt.u_max - Math.abs(pt.hyst || 0)) * 1000 } : null;
  const st = run?.state || {}, ph = PH[run?.phase] || PH.wait;
  const lastCyc = (st.cycles || []).filter((x) => x.t_return_s != null).slice(-1)[0];
  const curCyc = (st.cycles || []).slice(-1)[0];
  const phaseAge = st.phase_at ? (Date.now() - new Date(st.phase_at).getTime()) / 1000 : null;
  const stopMv = (p.delta_stop_v || 0) * 1000, ratio = c && stopMv ? Math.min(1.25, c.delta / stopMv) : 0;
  const over = c && stopMv && c.delta >= stopMv;
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 14, padding: "12px 16px", margin: "8px 0 16px", background: "var(--panel, transparent)" }}>
      <style>{`.bal-row{transition:top .9s cubic-bezier(.3,.8,.3,1)} .bal-move{transition:left .9s ease,width .9s ease}
        @keyframes balpulse{0%,100%{opacity:1}50%{opacity:.45}} @keyframes balflow{from{background-position:0 0}to{background-position:28px 0}}
        .bal-badge{animation:balpulse 1.6s ease-in-out infinite} .bal-flow{background-image:repeating-linear-gradient(110deg,rgba(255,255,255,.35) 0 7px,transparent 7px 14px);background-size:28px 100%;animation:balflow .9s linear infinite}
        .bal-in{width:92px;padding:5px 7px;border-radius:7px;border:1px solid var(--border);background:var(--bg,transparent);color:var(--fg);font-size:13.5px;font-variant-numeric:tabular-nums}
        @media (prefers-reduced-motion: reduce){.bal-row,.bal-move{transition:none}.bal-badge,.bal-flow{animation:none}}`}</style>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <b style={{ fontSize: 17 }}>⚖ Balancování {block.block_idx ? `B${block.block_idx}` : block.name}</b>
        {running
          ? <span className="bal-badge" style={{ background: ph.c, color: "#fff", fontWeight: 800, borderRadius: 999, padding: "4px 13px", fontSize: 13.5 }}>{ph.icon} {ph.name} · cyklus {run.cycle} · {dur(phaseAge)}{run.phase === "discharge" && curCyc?.t_discharge_plan_s > 0 ? ` z ${dur(curCyc.t_discharge_plan_s)}` : ""}</span>
          : <span className="muted" style={{ fontSize: 13 }}>{run && run.status !== "running" ? `poslední běh #${run.id}: ${run.result?.reason || run.status}` : "neběží"}</span>}
        <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {canCtl && !running && <button className="btn primary" onClick={start} disabled={!curForm || !c} style={{ fontWeight: 800, padding: "8px 18px", fontSize: 14, borderRadius: 10 }}>▶ Spustit balancování</button>}
          {canCtl && running && <button className="btn danger" onClick={stop} style={{ fontWeight: 800, padding: "8px 18px", fontSize: 14, borderRadius: 10 }}>■ Zastavit</button>}
          {!running && <button className="btn" onClick={() => setOpen(false)}>skrýt</button>}
        </span>
      </div>
      {msg && <div style={{ fontSize: 13, margin: "6px 0", color: msg.startsWith("⚠") ? "var(--red)" : "var(--green)" }}>{msg}</div>}

      {c && <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-end", margin: "12px 0 6px" }}>
        {isV && limit && <div style={{ minWidth: 250, flex: "1 1 250px", maxWidth: 420 }}>
          <div className="muted" style={{ fontSize: 11.5 }}>Nejvyšší článek vůči stropu bodu {running ? `${ptI + 1} z ${p.points.length}` : "1"} ({cs(limit.ulim / 1000, 3)} V{running ? `, cíl ${cs(pt.soc)} % SoC, cyklus ${Number(st.pt_cycles || 0) + 1}${pt.cycles ? ` z min. ${pt.cycles}` : ""}` : ""})</div>
          <div style={{ fontSize: 30, fontWeight: 800, color: c.max >= limit.thr ? HI : "var(--fg)", fontVariantNumeric: "tabular-nums", lineHeight: 1.15 }}>{cs(c.max / 1000, 3)} V
            <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}> · do stropu {cs(limit.ulim - c.max)} mV</span></div>
          <div style={{ position: "relative", height: 12, borderRadius: 6, background: "var(--border)", overflow: "hidden", marginTop: 4 }}>
            <div className={`bal-move${running && run.phase === "charge" ? " bal-flow" : ""}`} style={{ position: "absolute", inset: 0, borderRadius: 6,
                 width: `${Math.max(0, Math.min(100, ((c.max - (limit.ulim - 60)) / 75) * 100))}%`, backgroundColor: c.max >= limit.thr ? HI : "var(--green)" }} />
            <div style={{ position: "absolute", top: 0, bottom: 0, left: "80%", width: 2, background: "var(--fg)" }} title="strop bodu" />
            <div style={{ position: "absolute", top: 0, bottom: 0, left: `${((60 - (limit.ulim - limit.thr)) / 75) * 100}%`, width: 2, background: "var(--green)" }} title="strop − hystereze: odtud se snižuje výkon" />
          </div>
        </div>}
        {!isV && <div style={{ minWidth: 250, flex: "1 1 250px", maxWidth: 420 }}>
          <div className="muted" style={{ fontSize: 11.5 }}>Rozpětí článků max − min (mez {cs(stopMv)} mV)</div>
          <div style={{ fontSize: 30, fontWeight: 800, color: over ? HI : "var(--fg)", fontVariantNumeric: "tabular-nums", lineHeight: 1.15 }}>{cs(c.delta)} mV</div>
          <div style={{ position: "relative", height: 12, borderRadius: 6, background: "var(--border)", overflow: "hidden", marginTop: 4 }}>
            <div className={`bal-move${running && run.phase === "charge" ? " bal-flow" : ""}`} style={{ position: "absolute", inset: 0, width: `${(ratio / 1.25) * 100}%`, borderRadius: 6, backgroundColor: over ? HI : "var(--green)" }} />
            <div style={{ position: "absolute", top: 0, bottom: 0, left: "80%", width: 2, background: "var(--fg)" }} title="mez zastavení nabíjení" />
            {p.delta_final_v != null && stopMv > 0 && <div style={{ position: "absolute", top: 0, bottom: 0, left: `${((p.delta_final_v * 1000) / stopMv) * 80}%`, width: 2, background: "var(--green)" }} title="finální rozpětí" />}
          </div>
        </div>}
        {isV && <Stat label="Rozpětí článků">{cs(c.delta)} mV</Stat>}
        <Stat label="Nejvyšší článek" sub={`č. ${c.nmax} · box ${Math.ceil(c.nmax / c.per_module)}/${((c.nmax - 1) % c.per_module) + 1}`} color={HI}>{cs(c.max / 1000, 3)} V</Stat>
        <Stat label="Nejnižší článek" sub={`č. ${c.nmin} · box ${Math.ceil(c.nmin / c.per_module)}/${((c.nmin - 1) % c.per_module) + 1}`} color={LO}>{cs(c.min / 1000, 3)} V</Stat>
        <Stat label="Průměr článků">{cs(c.modules.reduce((s, m) => s + m.avg * m.mv.length, 0) / c.count / 1000, 3)} V</Stat>
        {running && <Stat label={isV ? "Nabíjecí výkon" : "Výkon cyklu"} sub={`povel teď ${cs(S.p_set[S.t.length - 1], 1)} kW`}>{cs(st.p_kw, 2)} kW</Stat>}
        {running && run.phase === "discharge" && curCyc?.t_discharge_plan_s > 0 &&
          <Stat label="Vybíjení — zbývá" color={HI} sub={`${cs(curCyc.p_dis_kw, 2)} kW · celkem ${dur(curCyc.t_discharge_plan_s)} (${cs(isV ? pt?.dis_t_ratio : p.dis_t_ratio, 2)} × ${dur(isV ? curCyc.t_last_s : curCyc.t_charge_s)})`}>{dur(Math.max(0, curCyc.t_discharge_plan_s - phaseAge))}</Stat>}
        {running && !isV && <Stat label="Doba návratu (posl.)" sub={`další nabíjení ${cs((st.p_kw || 0) * (p.chg_ratio ?? 0.5), 2)} kW`}>{lastCyc ? dur(lastCyc.t_return_s) : "—"}</Stat>}
        {running && isV && pt && <Stat label="Další schod výkonu" sub={`minimum bodu ${cs(pt.p_min_kw, 2)} kW`}>{Number(st.p_kw) <= pt.p_min_kw + 1e-6 ? "na minimu" : `${cs(Math.max(pt.p_min_kw, (st.p_kw || 0) * p.chg_ratio), 2)} kW`}</Stat>}
        {running && <Stat label="Od startu" sub={`SoC ${cs(S.soc[S.t.length - 1])} %`}>{dur((Date.now() - new Date(run.started_at).getTime()) / 1000)}</Stat>}
      </div>}

      {running && <BalanceChart S={S} params={p} live changes={st.params_log || []} />}
      {!running && (() => {                        // dočasný graf z živých snímků (jen po dobu otevřeného okna; nic se neukládá navíc)
        const h = localHist || [], L = EMPTY();
        for (const x of h) { let mx = -Infinity, mn = Infinity, sum = 0, imx = 0, imn = 0;
          x.mv.forEach((v, i) => { sum += v; if (v > mx) { mx = v; imx = i; } if (v < mn) { mn = v; imn = i; } });
          L.t.push(x.t); L.vmax.push(mx); L.vmin.push(mn); L.vavg.push(Math.round((sum / x.mv.length) * 10) / 10); L.delta.push(mx - mn); L.nmax.push(imx + 1); L.nmin.push(imn + 1);
          L.soc.push(x.soc); L.p_bat.push(x.pw != null ? x.pw / 1000 : null); L.p_set.push(null); L.phase.push(null); L.cycle.push(null); L.ulim.push(null); }
        return (<div style={{ marginTop: 6 }}>
          <div style={{ fontWeight: 700, fontSize: 13.5 }}>Živý průběh článků <span className="muted" style={{ fontWeight: 400 }}>— dočasný graf {h.length ? `od ${clock(h[0].t, false)}` : ""}, kreslí se jen z dat načtených po dobu otevřeného okna (po 5 s) a po zavření se zahodí</span></div>
          {h.length >= 2 ? <BalanceChart S={L} params={{ mode: "vmax" }} live /> : <div className="muted" style={{ fontSize: 13, padding: "18px 0" }}>Graf se začne kreslit po druhém snímku (do 10 s).</div>}
        </div>); })()}

      <details open style={{ margin: "10px 0" }}>
        <summary style={{ cursor: "pointer", fontWeight: 700, fontSize: 13.5 }}>Parametry {running ? "(lze měnit za běhu)" : "pro spuštění"}</summary>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", margin: "8px 0 2px" }}>
          <span className="muted" style={{ fontSize: 12.5 }}>Logika balancování:</span>
          {Object.entries(MODES).map(([k, lab]) => <button key={k} type="button" className="btn" disabled={running || !canCtl} onClick={() => { setMode(k); setDirty(false); }}
            title={running ? "Logiku lze změnit jen před spuštěním" : ""}
            style={{ fontWeight: mode === k ? 800 : 400, background: mode === k ? "#2a78d6" : undefined, color: mode === k ? "#fff" : undefined, borderRadius: 999, padding: "5px 14px" }}>{mode === k ? "● " : "○ "}{lab}</button>)}
        </div>
        {mode === "vmax" && formV && <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(215px, 1fr))", gap: "8px 16px", marginTop: 8 }}>
            {FIELDS_V.map(([k, lab, u, stp, tip]) => <label key={k} title={tip} style={{ fontSize: 12.5 }}>
              <div className="muted">{lab}</div>
              <input className="bal-in" type="number" step={stp} value={formV[k] ?? ""} disabled={!canCtl} onChange={(e) => { setFormV({ ...formV, [k]: e.target.value }); setDirty(true); }} /> {u}
            </label>)}
          </div>
          <div style={{ overflow: "auto", marginTop: 10 }}><table style={{ borderCollapse: "collapse", fontSize: 12.5 }}>
            <thead><tr><th className="muted" style={{ textAlign: "left", padding: "2px 8px 2px 0", fontWeight: 600 }}>bod</th>
              {POINT_COLS.map(([k, lab, , tip]) => <th key={k} title={tip} className="muted" style={{ textAlign: "left", padding: "2px 8px", fontWeight: 600 }}>{lab}</th>)}<th /></tr></thead>
            <tbody>{(formV.points || []).map((ptR, i) => <tr key={i} style={{ background: running && isV && i === ptI ? "color-mix(in srgb, var(--green) 14%, transparent)" : undefined }}>
              <td style={{ padding: "2px 8px 2px 0", fontWeight: 700, whiteSpace: "nowrap" }}>{i + 1}{running && isV && i === ptI ? " ◀ teď" : ""}</td>
              {POINT_COLS.map(([k, , stp]) => <td key={k} style={{ padding: "2px 8px" }}>
                <input className="bal-in" style={{ width: 84 }} type="number" step={stp} value={ptR[k] ?? ""} disabled={!canCtl} onChange={(e) => setPoint(i, k, e.target.value)} /></td>)}
              <td>{canCtl && formV.points.length > 1 && <button type="button" className="btn" style={{ padding: "1px 7px" }} title="odebrat bod"
                    onClick={() => { setFormV({ ...formV, points: formV.points.filter((_, j) => j !== i) }); setDirty(true); }}>✕</button>}</td>
            </tr>)}</tbody></table></div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 6 }}>
            {canCtl && (formV.points || []).length < 8 && <button type="button" className="btn" onClick={() => { const l = formV.points[formV.points.length - 1] || {};
              setFormV({ ...formV, points: [...formV.points, { ...l, soc: Math.min(100, Number(l.soc || 0) + 5), u_max: Math.min(3.6, Number(l.u_max || 3.3) + 0.03).toFixed(2) }] }); setDirty(true); }}>+ přidat bod</button>}
            <span className="muted" style={{ fontSize: 12 }}>Začíná se bodem podle aktuálního SoC. Na další bod se jde, až je odjetý min. počet cyklů a SoC dosáhlo hodnoty bodu. Poslední bod končí celé balancování.</span>
          </div>
        </>}
        {mode === "delta" && form && <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(215px, 1fr))", gap: "8px 16px", marginTop: 8 }}>
          {FIELDS.map(([k, lab, u, stp, tip]) => <label key={k} title={tip} style={{ fontSize: 12.5 }}>
            <div className="muted">{lab}</div>
            <input className="bal-in" type="number" step={stp} value={form[k] ?? ""} disabled={!canCtl}
                   onChange={(e) => { setForm({ ...form, [k]: e.target.value }); setDirty(true); }} /> {u}
            {u === "V" && k.startsWith("delta") && form[k] !== "" && <span className="muted"> = {cs(Number(form[k]) * 1000)} mV</span>}
          </label>)}
        </div>}
        {canCtl && <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
          {running && <button className="btn primary" onClick={apply} disabled={!dirty} style={{ fontWeight: 800 }}
                              title={dirty ? "Zapíše upravené hodnoty do běžícího balancování; platí od dalšího kroku" : "Nejdřív uprav některou hodnotu"}>✎ Změnit parametry balancování</button>}
          <button className="btn" onClick={fix}>📌 Zafixovat pro příští balancování</button>
          {dirty && running && <button className="btn" onClick={() => { (isV ? setFormV : setForm)(run.params); setDirty(false); }}>vrátit</button>}
        </div>}
      </details>

      {c && <><div style={{ fontWeight: 700, fontSize: 13.5, margin: "12px 0 6px" }}>Články seřazené podle napětí <span className="muted" style={{ fontWeight: 400 }}>
        — <span style={{ color: HI }}>●</span> nad průměrem, <span style={{ color: LO }}>●</span> pod průměrem; najetí = zvýraznění i v tabulce, klik = průběh článku; svislice = nejvyšší, nejnižší a průměr (čárkovaně); {isV ? "zelená čára = strop bodu, čárkovaná zelená = strop − hystereze" : "zelené pásmo = mez rozpětí od nejnižšího článku"}</span></div>
        <CellRuler cells={c} params={p} energy={running ? st.cell_e : null} limit={isV ? limit : null} hover={hover} onHover={onHover} onPick={onPick} /></>}

      {run && !running && run.result && <details style={{ marginTop: 12 }}><summary style={{ cursor: "pointer", fontWeight: 700, fontSize: 13.5 }}>Report posledního běhu #{run.id}</summary><Report run={run} /></details>}
      {running && (st.log || []).length > 0 && <details style={{ marginTop: 10 }}><summary style={{ cursor: "pointer", fontWeight: 700, fontSize: 13.5 }}>Záznam kroků ({st.log.length})</summary>
        <div style={{ fontSize: 12.5, maxHeight: 180, overflow: "auto", marginTop: 4 }}>{[...st.log].reverse().map((l, i) => <div key={i}><span className="muted">{clock(new Date(l.t).getTime())}</span> {l.text}</div>)}</div></details>}

      <details style={{ marginTop: 12 }} onToggle={(e) => e.currentTarget.open && loadHist()}>
        <summary style={{ cursor: "pointer", fontWeight: 700, fontSize: 13.5 }}>Historie balancování ({hist.length})</summary>
        {hist.length === 0 ? <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>Zatím žádný běh.</div>
          : <div style={{ overflow: "auto", marginTop: 6 }}><table style={{ fontSize: 12.5, borderCollapse: "collapse", minWidth: 720 }}>
            <thead><tr>{["#", "začátek", "trvání", "výsledek", "cyklů", "rozpětí mV", "výkon kW", "logika · meze", "spustil", ""].map((h) =>
              <th key={h} className="muted" style={{ textAlign: "left", padding: "3px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600 }}>{h}</th>)}</tr></thead>
            <tbody>{hist.map((h) => { const r = h.result || {}; return <tr key={h.id} style={{ background: past?.run.id === h.id ? "var(--border)" : undefined }}>
              {[h.id, new Date(h.started_at).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }), dur(r.duration_s),
                { done: "✓ dokončeno", stopped: "■ zastaveno", aborted: "⚠ přerušeno", running: "… běží" }[h.status] || h.status, cs(r.cycles ?? h.cycle),
                `${cs(r.delta_start_mv)} → ${cs(r.delta_end_mv)}`, `${cs(r.p_first_kw, 1)} → ${cs(r.p_last_kw, 1)}`,
                h.params.mode === "vmax" ? `napětí · ${(h.params.points || []).length} bodů do ${cs((h.params.points || []).slice(-1)[0]?.u_max, 2)} V`
                  : `rozpětí · ${cs(h.params.delta_stop_v * 1000)} / ${cs(h.params.delta_resume_v * 1000)} / ${cs((h.params.delta_final_v ?? 0) * 1000)} mV`, h.created_by || "—"].map((v, i) =>
                <td key={i} style={{ padding: "3px 10px", borderBottom: "1px solid var(--border)", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{v}</td>)}
              <td style={{ padding: "3px 10px", borderBottom: "1px solid var(--border)" }}><button className="btn" style={{ padding: "1px 9px" }} onClick={() => (past?.run.id === h.id ? setPast(null) : openPast(h.id))}>{past?.run.id === h.id ? "zavřít" : "křivka a report"}</button></td>
            </tr>; })}</tbody></table></div>}
        {past && <div style={{ marginTop: 10, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
          <b style={{ fontSize: 14 }}>Běh #{past.run.id} · {new Date(past.run.started_at).toLocaleString("cs-CZ")}</b>
          <BalanceChart S={past.S} params={past.run.params} live={false} changes={past.run.state?.params_log || []} />
          <Report run={past.run} />
          {(past.run.state?.log || []).length > 0 && <details style={{ marginTop: 6 }}><summary style={{ cursor: "pointer", fontSize: 13 }}>Záznam kroků ({past.run.state.log.length})</summary>
            <div style={{ fontSize: 12.5, maxHeight: 220, overflow: "auto" }}>{past.run.state.log.map((l, i) => <div key={i}><span className="muted">{clock(new Date(l.t).getTime())}</span> {l.text}</div>)}</div></details>}
        </div>}
      </details>
    </div>);
}
