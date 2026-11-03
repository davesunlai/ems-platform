// 🚗 Wallbox — panel po kliknutí na uzel ve schématu (Dashboard) a karta v Ovládání (sdílené).
// Živý stav, historie relací, kWh po dnech; řízení jen s právem control; nastavení modulu jen admin.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { CarCard } from "./CarCards";

// go-e car: 1 = bez auta, 2 = nabíjí, 3 = připojeno a čeká na auto, 4 = připojeno, nenabíjí (auto nežádá / plné / pauza) — „Complete" u go-e NEZNAMENÁ plnou baterii
export const EV_CAR = { idle: "bez auta", charging: "⚡ nabíjí", wait_car: "🔌 připojeno · čeká na auto", complete: "🔌 připojeno · nenabíjí", error: "⛔ chyba", unknown: "?" };
const FLD = { padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };
const dt = (iso) => (iso ? new Date(iso).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const dur = (s) => (s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min` : `${Math.round(s / 60)} min`);

// Řízení (cíl EMS = proud / fáze / start-stop; uvolnit = frc=0)
export function EvControl({ mod, live, onSent }) {
  const { has } = useAuth();
  const [st, setSt] = useState(null);
  const [amp, setAmp] = useState("");
  const [psm, setPsm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const refresh = () => api.controlStates(mod.id).then((r) => setSt((r?.states || {})[mod.id] || null)).catch(() => {});
  useEffect(() => { refresh(); const t = setInterval(refresh, 10000); return () => clearInterval(t); /* eslint-disable-next-line */ }, [mod.id]);
  // předvyplnit AKTUÁLNÍ hodnoty (cíl EMS, jinak co je na nabíječce) — ne default
  useEffect(() => {
    const t = st?.action === "ev_set" ? (st.params?.target || {}) : {};
    if (amp === "" && (t.amp ?? live?.amp_set) != null) setAmp(t.amp ?? live.amp_set);
    if (psm == null && (t.psm ?? live?.phase_mode) != null) setPsm(t.psm ?? live.phase_mode);
    /* eslint-disable-next-line */ }, [st, live]);
  const send = async (action, params, label) => {
    setBusy(true); setMsg("");
    try { await api.enqueueCommand(mod.id, action, { ...params, source: "manual", reason: label }); setMsg(`${label} — odesláno`); setTimeout(() => { refresh(); onSent && onSent(); }, 4000); }
    catch (e) { setMsg("Chyba: " + e.message); }
    setBusy(false);
  };
  const tgt = st?.action === "ev_set" ? (st.params?.target || {}) : null;
  const estKw = (a, p) => ((p === 1 ? 1 : 3) * 230 * a / 1000).toFixed(1);
  return (
    <div>
      <div style={{ fontSize: 12.5 }}>řízení: <b>{tgt ? `EMS ${tgt.frc === 2 ? "NABÍJET" : tgt.frc === 1 ? "PAUZA" : "neutral"}${tgt.amp ? ` ${tgt.amp} A` : ""}${tgt.psm ? ` ${tgt.psm === 1 ? "1f" : "3f"}` : ""}` : "uvolněno (nabíječka sama)"}</b>{st?.params?.source && tgt ? <span className="muted"> · {st.params.source}</span> : null}
        {live?.amp_allowed != null && live?.amp_set != null && live.amp_allowed < live.amp_set && <span style={{ color: "var(--amber)", marginLeft: 8 }}>⚠ nabíječka omezuje na {live.amp_allowed} A</span>}</div>
      {has("control") ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6, flexWrap: "wrap" }}>
          <select style={FLD} value={psm ?? 0} onChange={(e) => setPsm(Number(e.target.value))}>
            <option value={1}>1 fáze</option><option value={2}>3 fáze</option><option value={0}>auto</option>
          </select>
          <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6, flex: "1 1 220px", minWidth: 220 }}>
            <span>6 A</span>
            <style>{`.ev-range{height:34px;-webkit-appearance:none;appearance:none;background:transparent}
.ev-range::-webkit-slider-runnable-track{height:8px;border-radius:4px;background:var(--border)}
.ev-range::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;width:36px;height:36px;border-radius:50%;background:var(--green);border:3px solid var(--bg);margin-top:-14px;cursor:grab;box-shadow:0 1px 4px rgba(0,0,0,.4)}
.ev-range::-moz-range-track{height:8px;border-radius:4px;background:var(--border)}
.ev-range::-moz-range-thumb{width:36px;height:36px;border-radius:50%;background:var(--green);border:3px solid var(--bg);cursor:grab}`}</style>
            <input type="range" className="ev-range" min={6} max={live?.amp_max || 32} step={1} value={Number(amp) || 6} style={{ flex: 1 }}
                   onChange={(e) => setAmp(Number(e.target.value))} title="výkon po 1 A" />
            <span>{live?.amp_max || 32} A</span>
          </label>
          <span style={{ fontSize: 13, minWidth: 120 }}><b>{Number(amp) || 0} A</b> ≈ <b>{estKw(Number(amp) || 0, psm ?? 0)} kW</b>{(psm ?? 0) === 0 ? <span className="muted"> (3f)</span> : null}</span>
          <button className="btn primary" disabled={busy || !(Number(amp) >= 6)} onClick={() => send("ev_set", { amp: Number(amp), psm: psm ?? 0, frc: 2 }, `nabíjet ${amp} A ${psm === 1 ? "1f" : psm === 2 ? "3f" : "auto"}`)}>⚡ Nabíjet</button>
          <button className="btn" disabled={busy} onClick={() => send("ev_set", { frc: 1 }, "pauza")}>⏸ Pauza</button>
          <button className="btn" disabled={busy} onClick={() => send("ev_release", {}, "uvolnit řízení")}>↺ Uvolnit</button>
          {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
        </div>
      ) : <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>Řízení nabíječky vyžaduje právo ovládání.</p>}
      <p className="muted" style={{ fontSize: 11.5, margin: "6px 0 0" }}>
        Zápis na nabíječku jen při změně (proud/fáze ≥ 60 s od sebe, přepnutí fází nejdřív po 10 min — vynucuje nabíječka). Po restartu nabíječky se cíl obnoví;
        po výpadku spojení &gt; 5 min nebo vypnutí TERA se řízení uvolní, aby auto nezůstalo zamčené.
      </p>
    </div>
  );
}

// Celý panel (modal na dashboardu): stav + řízení + historie
// Měsíční sloupcový graf: den = celková energie (z čítače), uvnitř dílky = relace začínající ten den.
function MonthChart({ month, daily, runs, onDay }) {
  const [y, m] = month.split("-").map(Number);
  const nDays = new Date(y, m, 0).getDate();
  const byDay = {};
  daily.forEach((x) => { byDay[Number(x.day.slice(8, 10))] = x.kwh || 0; });
  const segs = {};
  (runs || []).forEach((r, idx) => {
    const dn = Number(r.day.slice(8, 10));
    if (r.day.slice(0, 7) !== month) return;
    (segs[dn] = segs[dn] || []).push({ kwh: r.kwh, id: idx, t: new Date(r.start), ph: r.phases });
  });
  const totals = Array.from({ length: nDays }, (_, i) => Math.max(byDay[i + 1] || 0, (segs[i + 1] || []).reduce((a, b) => a + b.kwh, 0)));
  const maxV = Math.max(5, ...totals);
  const step = maxV <= 10 ? 2 : maxV <= 30 ? 5 : maxV <= 60 ? 10 : 20;
  const top = Math.ceil(maxV / step) * step;
  const W = 1400, H = 300, L = 44, B = 30, T = 16, R = 8;
  const cw = (W - L - R) / nDays, bw = cw * 0.78;
  const yv = (v) => T + (H - T - B) * (1 - v / top);
  const COLORS = ["#3fb950", "#58a6ff", "#a371f7", "#d29922", "#39c5cf"];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", margin: "6px 0 10px" }}>
      {Array.from({ length: top / step + 1 }, (_, i) => i * step).map((v) => (
        <g key={v}><line x1={L} x2={W - R} y1={yv(v)} y2={yv(v)} stroke="var(--border)" strokeWidth="0.6" />
          <text x={L - 4} y={yv(v) + 3} textAnchor="end" fontSize="9" fill="var(--muted)">{v}</text></g>))}
      <text x={6} y={T + 4} fontSize="9" fill="var(--muted)">kWh</text>
      {totals.map((tot, i) => {
        const x = L + i * cw + (cw - bw) / 2;
        const sg = (segs[i + 1] || []).slice().sort((a, b) => a.t - b.t);
        const n = sg.length, sw = n ? Math.max(3, (bw - 2 * (n - 1)) / n) : 0;
        const dayIso = `${month}-${String(i + 1).padStart(2, "0")}`;
        return (
          <g key={i} onClick={() => onDay && onDay(dayIso)} style={{ cursor: "pointer" }}>
            <rect x={L + i * cw} y={T} width={cw} height={H - T - B} fill="transparent" />
            {/* celkem za den — světlý široký sloupec v pozadí */}
            {tot > 0.05 && <rect x={x} y={yv(tot)} width={bw} height={Math.max(1, yv(0) - yv(tot))} fill="var(--green)" opacity="0.22" rx="2" />}
            {tot <= 0.05 && <rect x={x} y={yv(0) - 1} width={bw} height={1} fill="var(--muted)" opacity="0.5" />}
            {/* relace — tenké sloupečky vedle sebe, každý od nuly */}
            {sg.map((s, j) => { const sx = x + j * (sw + 2), y0 = yv(s.kwh), h = yv(0) - y0;
              // popisek: vedle sebe, když se vejde (šířka ≈ 4,2 px/znak); jinak NAD SEBOU (schodovitě), vždy centrovaný na svůj sloupeček
              const lbl = s.kwh.toFixed(1), lw = lbl.length * 4.6, fits = sw >= lw;
              const ly = fits ? y0 - 2 : y0 - 2 - (n - 1 - j) * 9;
              return <g key={s.id}><rect x={sx} y={y0} width={sw} height={Math.max(1, h)} fill={COLORS[j % COLORS.length]} rx="1.5" />
                <title>{`${s.t.toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })} · ${s.kwh.toFixed(1)} kWh · ${s.ph || "?"}f`}</title>
                {!fits && <line x1={sx + sw / 2} x2={sx + sw / 2} y1={ly + 1} y2={y0} stroke={COLORS[j % COLORS.length]} strokeWidth="0.6" opacity="0.8" />}
                <text x={sx + sw / 2} y={ly} textAnchor="middle" fontSize="7.5" fill={COLORS[j % COLORS.length]} fontWeight="600">{lbl}</text></g>; })}
            {(() => { const lblTop = n ? Math.min(...sg.map((s, j) => (sw >= s.kwh.toFixed(1).length * 4.6 ? yv(s.kwh) - 2 : yv(s.kwh) - 2 - (n - 1 - j) * 9))) : yv(tot);
              const ty = Math.min(yv(tot) - 3, lblTop - 9);
              return <text x={x + bw / 2} y={Math.max(T + 8, ty)} textAnchor="middle" fontSize="9" fontWeight="700" fill="var(--fg)">{tot > 0.05 ? tot.toFixed(tot >= 10 ? 0 : 1) : ""}</text>; })()}
            <text x={x + bw / 2} y={H - B + 12} textAnchor="middle" fontSize="9" fill="var(--muted)">{i + 1}.</text>
          </g>);
      })}
      <text x={(L + W - R) / 2} y={H - 4} textAnchor="middle" fontSize="9" fill="var(--muted)">den v měsíci</text>
    </svg>
  );
}

// Detail dne: průběh výkonu po minutě + úseky nabíjení + relace
// 🗺 Mapa polohy nabíjení (OpenStreetMap embed + odkaz do Google Maps)
export function MapModal({ lat, lon, title, onClose }) {
  const dlt = 0.004;
  const bbox = `${lon - dlt * 1.6},${lat - dlt},${lon + dlt * 1.6},${lat + dlt}`;
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.65)", zIndex: 120, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} className="panel" style={{ width: "min(760px, 96vw)", padding: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <b>📍 {title || "Poloha nabíjení"}</b>
          <span className="muted" style={{ fontSize: 12 }}>{lat.toFixed(5)}, {lon.toFixed(5)}</span>
          <a className="btn" style={{ marginLeft: "auto", padding: "2px 8px", fontSize: 12 }} href={`https://maps.google.com/?q=${lat},${lon}`} target="_blank" rel="noreferrer">Google Maps ↗</a>
          <button className="btn" style={{ padding: "2px 8px" }} onClick={onClose}>✕</button>
        </div>
        <iframe title="mapa" style={{ width: "100%", height: "min(420px, 60vh)", border: "1px solid var(--border)", borderRadius: 8, marginTop: 8 }}
                src={`https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lon}`} />
      </div>
    </div>
  );
}

function DayDetail({ locId, date, onClose }) {
  const [d, setD] = useState(null);
  const [carS, setCarS] = useState([]);           // relace aut (CarData) v tento den — s GPS
  const [tip, setTip] = useState(null);            // {x, y, run|car}
  const [map, setMap] = useState(null);            // {lat, lon, title}
  useEffect(() => {
    setD(null); setCarS([]);
    api.evDay(locId, date).then(setD).catch(() => setD({ series: [], runs: [], sessions: [] }));
    api.carsSessions(locId, `date=${date}`).then((r) => setCarS(r || [])).catch(() => {});
  }, [locId, date]);
  // poloha k úseku wallboxu = relace auta, která se s ním časově překrývá (auto posílá GPS při zapojení)
  const overlaps = (c, s, e) => new Date(c.start) <= new Date(e || Date.now()) && new Date(c.end || Date.now()) >= new Date(s);
  const carAny = (r) => (r.car_name ? { name: r.car_name } : carS.find((c) => overlaps(c, r.start, r.end)));   // auto z relace wallboxu, jinak překryv s CarData
  const carFor = (r) => carS.find((c) => c.lat != null && overlaps(c, r.start, r.end));    // totéž, ale s GPS
  const showTip = (e, body) => { const b = e.currentTarget.ownerSVGElement.getBoundingClientRect(); setTip({ x: e.clientX - b.left, y: e.clientY - b.top, body }); };
  // křížový kurzor: svislá čára + tečka na křivce + box s hodnotami v daném čase (jako u ostatních grafů)
  const [cur, setCur] = useState(null);
  const onMove = (e) => {
    const ser = d?.series || []; if (!ser.length) return;
    const b = e.currentTarget.getBoundingClientRect();
    const px = (e.clientX - b.left) * (W / b.width);
    const t = new Date(t0.getTime() + Math.max(0, Math.min(1, (px - L) / (W - L - R))) * dayMs);
    let best = 0, bd = Infinity;
    ser.forEach((p, i) => { const dd = Math.abs(new Date(p.ts) - t); if (dd < bd) { bd = dd; best = i; } });
    const p = ser[best];
    const run = (d.runs || []).find((r) => new Date(r.start) <= t && new Date(r.end) >= t);
    const car = run ? carAny(run) : carS.find((c) => overlaps(c, t.toISOString(), t.toISOString()));
    setCur({ x: e.clientX - b.left, y: e.clientY - b.top, p, t, run, car, far: bd > 15 * 60000 });
  };
  const W = 1400, H = 220, L = 44, B = 26, T = 12, R = 8;
  const ser = d?.series || [];
  const maxKw = Math.max(4, ...ser.map((p) => (p.power_w || 0) / 1000));
  const top = Math.ceil(maxKw / 2) * 2;
  const t0 = new Date(`${date}T00:00:00`); const dayMs = 86400000;
  const xs = (iso) => L + (W - L - R) * Math.max(0, Math.min(1, (new Date(iso) - t0) / dayMs));
  const yv = (kw) => T + (H - T - B) * (1 - kw / top);
  const path = ser.length ? ser.map((p, i) => `${i ? "L" : "M"}${xs(p.ts).toFixed(1)},${yv((p.power_w || 0) / 1000).toFixed(1)}`).join(" ") : "";
  const tm = (iso) => new Date(iso).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 10, margin: "4px 0 12px", position: "relative" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <b style={{ fontSize: 13 }}>📅 {new Date(date).toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "long" })}</b>
        {d && <span className="muted" style={{ fontSize: 12 }}>úseků nabíjení: {d.runs.length} · celkem {d.kwh_runs ?? 0} kWh</span>}
        <button className="btn" style={{ marginLeft: "auto", padding: "1px 8px" }} onClick={onClose}>✕</button>
      </div>
      {!d ? <p className="muted">Načítám…</p> : (<>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", marginTop: 6 }} onMouseMove={onMove} onMouseLeave={() => setCur(null)}>
          {Array.from({ length: top / 2 + 1 }, (_, i) => i * 2).map((v) => (
            <g key={v}><line x1={L} x2={W - R} y1={yv(v)} y2={yv(v)} stroke="var(--border)" strokeWidth="0.6" />
              <text x={L - 4} y={yv(v) + 3} textAnchor="end" fontSize="9" fill="var(--muted)">{v}</text></g>))}
          <text x={6} y={T + 4} fontSize="9" fill="var(--muted)">kW</text>
          {Array.from({ length: 25 }, (_, h) => h).map((h) => (
            <g key={h}><line x1={L + (W - L - R) * h / 24} x2={L + (W - L - R) * h / 24} y1={H - B} y2={H - B + 4} stroke="var(--muted)" />
              {h % 2 === 0 && <text x={L + (W - L - R) * h / 24} y={H - B + 14} textAnchor="middle" fontSize="9" fill="var(--muted)">{h}:00</text>}</g>))}
          {carS.map((c, i) => (
            <rect key={`c${i}`} x={xs(c.start)} y={T} width={Math.max(2, xs(c.end || new Date().toISOString()) - xs(c.start))} height={H - T - B}
                  fill="#58a6ff" opacity="0.14" style={{ cursor: "pointer" }}
                  onMouseEnter={(e) => showTip(e, { kind: "car", c })} onMouseLeave={() => setTip(null)}
                  onClick={() => c.lat != null && setMap({ lat: c.lat, lon: c.lon, title: `${c.name} · ${tm(c.start)}–${c.end ? tm(c.end) : "…"}` })} />))}
          {d.runs.map((r, i) => (
            <rect key={i} x={xs(r.start)} y={T} width={Math.max(1, xs(r.end) - xs(r.start))} height={H - T - B} fill="var(--green)" opacity="0.12" style={{ cursor: "pointer" }}
                  onMouseEnter={(e) => showTip(e, { kind: "run", r, c: carFor(r) })} onMouseLeave={() => setTip(null)}
                  onClick={() => { const c = carFor(r); if (c) setMap({ lat: c.lat, lon: c.lon, title: `wallbox · ${tm(r.start)}–${tm(r.end)}` }); }} />))}
          {path && <path d={path} fill="none" stroke="var(--green)" strokeWidth="1.6" />}
          {cur && !cur.far && (<g pointerEvents="none">
            <line x1={xs(cur.p.ts)} x2={xs(cur.p.ts)} y1={T} y2={H - B} stroke="var(--fg)" strokeWidth="0.8" strokeDasharray="3 3" opacity="0.6" />
            <circle cx={xs(cur.p.ts)} cy={yv((cur.p.power_w || 0) / 1000)} r="4" fill="var(--green)" stroke="var(--bg)" strokeWidth="1.5" />
          </g>)}
        </svg>
        {cur && !cur.far && !tip && (
          <div style={{ position: "absolute", left: cur.x > 600 ? cur.x - 230 : cur.x + 14, top: cur.y + 30, background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 8,
                        padding: "6px 10px", fontSize: 12, pointerEvents: "none", zIndex: 5, boxShadow: "0 4px 14px rgba(0,0,0,.4)", minWidth: 190 }}>
            <div><b>{tm(cur.p.ts)}</b> · <b style={{ color: "var(--green)" }}>{((cur.p.power_w || 0) / 1000).toFixed(2)} kW</b>{cur.p.amp_set != null ? ` · ${cur.p.amp_set} A` : ""}{cur.run?.phases ? ` · ${cur.run.phases}f` : ""}</div>
            {cur.car && <div>🚘 <b>{cur.car.name}</b>{cur.car.soc_from != null ? ` · ${Math.round(cur.car.soc_from)} → ${Math.round(cur.car.soc_to)} %` : ""}</div>}
            {cur.run && <div className="muted">úsek {tm(cur.run.start)}–{tm(cur.run.end)} · {cur.run.kwh.toFixed(2)} kWh · max {cur.run.max_kw} kW</div>}
            {!cur.run && <div className="muted">mimo nabíjení</div>}
          </div>)}
        {tip && (
          <div style={{ position: "absolute", left: Math.min(tip.x + 12, 900), top: tip.y + 36, background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 8,
                        padding: "6px 10px", fontSize: 12, pointerEvents: "none", zIndex: 5, boxShadow: "0 4px 14px rgba(0,0,0,.4)" }}>
            {tip.body.kind === "run" ? (<>
              <b>🚗 wallbox{carAny(tip.body.r) ? ` · 🚘 ${carAny(tip.body.r).name}` : ""}</b> {tm(tip.body.r.start)}–{tm(tip.body.r.end)} · <b>{tip.body.r.kwh.toFixed(2)} kWh</b> · max {tip.body.r.max_kw} kW
              <div className="muted">{tip.body.c ? "📍 klikni pro mapu" : carAny(tip.body.r) ? "📍 poloha: doma (wallbox)" : "🚘 auto neurčeno (relace před připojením CarData)"}</div>
            </>) : (<>
              <b>🚘 {tip.body.c.name}</b> {tm(tip.body.c.start)}–{tip.body.c.end ? tm(tip.body.c.end) : "probíhá"}
              {tip.body.c.soc_from != null && <> · {Math.round(tip.body.c.soc_from)} → {Math.round(tip.body.c.soc_to)} %</>}
              {tip.body.c.kwh != null && <> · <b>≈ {tip.body.c.kwh} kWh</b></>}{tip.body.c.max_kw != null && <> · max {tip.body.c.max_kw} kW</>}
              <div className="muted">{tip.body.c.lat != null ? "📍 klikni pro mapu polohy nabíječky" : "📍 poloha nepřišla"}</div>
            </>)}
          </div>)}
        {map && <MapModal {...map} onClose={() => setMap(null)} />}
        <table style={{ fontSize: 12, width: "100%" }}>
          <thead><tr><th>#</th><th>Auto</th><th>Od</th><th>Do</th><th>Trvání</th><th>kWh</th><th>Ø kW</th><th>max kW</th><th>fáze</th></tr></thead>
          <tbody>{d.runs.map((r, i) => (
            <tr key={i}><td>{i + 1}</td><td>{carAny(r) ? <b>🚘 {carAny(r).name}</b> : <span className="muted">—</span>}</td><td>{tm(r.start)}</td><td>{tm(r.end)}</td><td>{dur((new Date(r.end) - new Date(r.start)) / 1000)}</td>
              <td><b>{r.kwh.toFixed(2)}</b></td><td>{r.avg_kw}</td><td>{r.max_kw}</td><td>{r.phases || "—"}</td></tr>))}
            {!d.runs.length && <tr><td colSpan={9} className="muted">V tento den se na wallboxu nenabíjelo.</td></tr>}
          </tbody></table>
        {carS.length > 0 && (
          <table style={{ fontSize: 12, width: "100%", marginTop: 8 }}>
            <thead><tr><th>🚘 Auto (CarData)</th><th>Od</th><th>Do</th><th>SoC</th><th>≈ kWh</th><th>max kW</th><th>Poloha</th></tr></thead>
            <tbody>{carS.map((c, i) => (
              <tr key={i}><td>{c.name}</td><td>{tm(c.start)}</td><td>{c.end ? tm(c.end) : "probíhá"}</td>
                <td>{c.soc_from != null ? `${Math.round(c.soc_from)} → ${c.soc_to != null ? Math.round(c.soc_to) : "?"} %` : "—"}</td>
                <td><b>{c.kwh ?? "—"}</b></td><td>{c.max_kw ?? "—"}</td>
                <td>{c.lat != null ? <a href="#map" onClick={(e) => { e.preventDefault(); setMap({ lat: c.lat, lon: c.lon, title: `${c.name} · ${tm(c.start)}` }); }}>📍 mapa</a> : <span className="muted">—</span>}</td></tr>))}
            </tbody></table>)}
        {d.sessions.length > 0 && <p className="muted" style={{ fontSize: 11.5, margin: "6px 0 0" }}>
          Relace (připojení kabelu) zasahující do dne: {d.sessions.map((s) => `${dt(s.started_at)} → ${s.ended_at ? dt(s.ended_at) : "probíhá"} (${(((s.wh ?? s.wh_max) || 0) / 1000).toFixed(1)} kWh)`).join(" · ")}</p>}
      </>)}
    </div>
  );
}

export function EvPanel({ locId, mod, onClose }) {
  const { has } = useAuth();
  const [live, setLive] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [daily, setDaily] = useState([]);
  const [runs, setRuns] = useState([]);
  const [day, setDay] = useState(null);           // rozkliknutý den (YYYY-MM-DD)
  const [cars, setCars] = useState([]);
  const [carM, setCarM] = useState([]);           // relace aut (CarData) za měsíc → které auto nabíjelo na wallboxu
  const carOfSession = (s) => (s.car_name ? { name: s.car_name } : carM.find((c) => new Date(c.start) <= new Date(s.ended_at || Date.now()) && new Date(c.end || Date.now()) >= new Date(s.started_at)));
  const [month, setMonth] = useState(() => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}`; });
  const load = () => {
    api.evState(locId).then((r) => setLive(r.state)).catch(() => {});
    api.carsVehicles(locId).then(setCars).catch(() => {});
    api.evSessionsMonth(locId, month).then(setSessions).catch(() => {});
    api.carsSessions(locId, `month=${month}`).then((r) => setCarM(r || [])).catch(() => {});
    api.evMonth(locId, month).then((r) => { setDaily(r.daily || []); setRuns(r.runs || []); }).catch(() => {});
  };
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); /* eslint-disable-next-line */ }, [locId, month]);
  const kw = live?.power_w != null ? (live.power_w / 1000).toFixed(1) : "?";
  const shiftMonth = (k) => { const [y, m] = month.split("-").map(Number); const d = new Date(y, m - 1 + k, 1); setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`); };
  const monthLabel = (() => { const [y, m] = month.split("-").map(Number); return new Date(y, m - 1, 1).toLocaleDateString("cs-CZ", { month: "long", year: "numeric" }); })();
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 95, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} className="panel" style={{ width: "98vw", maxWidth: "none", maxHeight: "94vh", overflow: "auto", padding: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <b style={{ fontSize: 15 }}>🚗 Wallbox — {mod?.name || mod?.id || "nabíječka"}</b>
          {has("admin") && mod?.id && <Link to="/modules" className="muted" style={{ fontSize: 12 }} title="nastavení modulu (IP, max A při 1f/3f)">⚙ nastavení modulu</Link>}
          {mod?.id && <Link to={`/diagnostics/${mod.id}`} className="muted" style={{ fontSize: 12 }}>🔬 diagnostika</Link>}
          <button className="btn" style={{ marginLeft: "auto", padding: "3px 10px" }} onClick={onClose}>✕</button>
        </div>
        {live ? (
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", margin: "8px 0", fontSize: 13 }}>
            <span>{EV_CAR[live.car_state] || live.car}</span>
            <span>výkon <b style={{ color: live.power_w > 50 ? "var(--green)" : "var(--fg)" }}>{kw} kW</b>{live.phases_active ? ` (${live.phases_active}f)` : ""}</span>
            <span>proud {live.amp_set} A{live.amp_allowed != null && live.amp_allowed !== live.amp_set ? ` (povoleno ${live.amp_allowed})` : ""}</span>
            <span>relace <b>{((live.session_wh || 0) / 1000).toFixed(1)} kWh</b></span>
            <span>celkem {((live.energy_total_wh || 0) / 1000).toFixed(0)} kWh</span>
            <span className="muted" title="modelStatus">{live.model_status_cz}</span>
            {live.error ? <span style={{ color: "#f85149" }}>⛔ chyba {live.error}</span> : null}
            {live.temp_c != null && <span className="muted">{Number(live.temp_c).toFixed(0)} °C</span>}
          </div>
        ) : <p className="muted">Načítám…</p>}
        {mod?.id && <div style={{ padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 10 }}><EvControl mod={mod} live={live} onSent={load} /></div>}
        {cars.length > 0 && (<>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}><b style={{ fontSize: 13 }}>🚘 Auta</b>{has("admin") && <Link to="/cars" className="muted" style={{ fontSize: 12 }}>⚙ účet a mapování</Link>}</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 10, margin: "6px 0 12px" }}>{cars.map((c) => <CarCard key={c.vin} car={c} />)}</div>
        </>)}

        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
          <b style={{ fontSize: 13 }}>Nabito po dnech</b>
          <button className="btn" style={{ padding: "1px 8px" }} onClick={() => shiftMonth(-1)} title="předchozí měsíc">◀</button>
          <span style={{ fontSize: 13, minWidth: 120, textAlign: "center" }}>{monthLabel}</span>
          <button className="btn" style={{ padding: "1px 8px" }} onClick={() => shiftMonth(1)} title="další měsíc">▶</button>
          <span className="muted" style={{ fontSize: 11.5 }}>světlý sloupec = celkem za den (kWh) · tenké sloupečky od nuly = jednotlivé úseky nabíjení (pauza = nový úsek) · klik na den = detail</span>
        </div>
        <MonthChart month={month} daily={daily} runs={runs} onDay={setDay} />
        {day && <DayDetail locId={locId} date={day} onClose={() => setDay(null)} />}

        <b style={{ fontSize: 13 }}>Historie relací</b>
        {sessions.length ? (
          <table style={{ fontSize: 12, marginTop: 6, width: "100%" }}>
            <thead><tr><th>Auto</th><th>Od</th><th>Do</th><th>Nabíjení</th><th>kWh</th><th>max kW</th><th>fáze</th><th>ze sítě</th><th>z FVE/baterie</th><th>Kč</th><th>konec</th></tr></thead>
            <tbody>{sessions.map((s) => (
              <tr key={s.id}>
                <td>{carOfSession(s) ? <b>🚘 {carOfSession(s).name}</b> : <span className="muted">—</span>}</td>
                <td>{dt(s.started_at)}</td><td>{s.ended_at ? dt(s.ended_at) : <b style={{ color: "var(--green)" }}>probíhá</b>}</td>
                <td>{dur(s.charging_s || 0)}</td><td><b>{(((s.wh ?? s.wh_max) || 0) / 1000).toFixed(1)}</b></td>
                <td>{((s.max_power_w || 0) / 1000).toFixed(1)}</td><td>{s.phases || "—"}</td>
                <td>{(s.grid_kwh || 0).toFixed(1)}</td><td>{(s.pv_kwh || 0).toFixed(1)}</td><td>{(s.cost_czk || 0).toFixed(0)}</td>
                <td className="muted">{{ unplugged: "odpojeno", complete: "nabito", error: "chyba", orphan: "ztraceno" }[s.ended_reason] || ""}</td>
              </tr>))}
            </tbody></table>
        ) : <p className="muted" style={{ fontSize: 12 }}>Zatím žádná relace (začne připojením auta).</p>}
        <p className="muted" style={{ fontSize: 11, marginTop: 8 }}>ze sítě / z FVE+baterie = rozdělení podle okamžitého importu lokality během nabíjení (v noci je „z FVE/baterie" = z domácí baterie); Kč = síťová část × efektivní cena importu z ceníku. Relace = jedno připojení kabelu; úseky nabíjení uvnitř relace jsou v grafu a v detailu dne.</p>
      </div>
    </div>
  );
}
