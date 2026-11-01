// 🚗 Wallbox — panel po kliknutí na uzel ve schématu (Dashboard) a karta v Ovládání (sdílené).
// Živý stav, historie relací, kWh po dnech; řízení jen s právem control; nastavení modulu jen admin.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

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
            <input type="range" min={6} max={live?.amp_max || 32} step={1} value={Number(amp) || 6} style={{ flex: 1 }}
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
function MonthChart({ month, daily, sessions }) {
  const [y, m] = month.split("-").map(Number);
  const nDays = new Date(y, m, 0).getDate();
  const byDay = {};
  daily.forEach((x) => { byDay[Number(x.day.slice(8, 10))] = x.kwh || 0; });
  const segs = {};
  sessions.forEach((s) => {
    const d = new Date(s.started_at); if (d.getFullYear() !== y || d.getMonth() + 1 !== m) return;
    const k = (((s.wh ?? s.wh_max) || 0) / 1000);
    if (k > 0.05) (segs[d.getDate()] = segs[d.getDate()] || []).push({ kwh: k, id: s.id, t: d });
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
        return (
          <g key={i}>
            {/* celkem za den — světlý široký sloupec v pozadí */}
            {tot > 0.05 && <rect x={x} y={yv(tot)} width={bw} height={Math.max(1, yv(0) - yv(tot))} fill="var(--green)" opacity="0.22" rx="2" />}
            {tot <= 0.05 && <rect x={x} y={yv(0) - 1} width={bw} height={1} fill="var(--muted)" opacity="0.5" />}
            {/* relace — tenké sloupečky vedle sebe, každý od nuly */}
            {sg.map((s, j) => { const sx = x + j * (sw + 2), y0 = yv(s.kwh), h = yv(0) - y0;
              return <g key={s.id}><rect x={sx} y={y0} width={sw} height={Math.max(1, h)} fill={COLORS[j % COLORS.length]} rx="1.5" />
                <title>{`${s.t.toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })} · ${s.kwh.toFixed(1)} kWh`}</title>
                {h > 12 && sw > 14 && <text x={sx + sw / 2} y={y0 - 2} textAnchor="middle" fontSize="7.5" fill="var(--fg)">{s.kwh.toFixed(1)}</text>}</g>; })}
            <text x={x + bw / 2} y={yv(tot) - (n ? 12 : 3)} textAnchor="middle" fontSize="9" fontWeight="700" fill="var(--fg)">{tot > 0.05 ? tot.toFixed(tot >= 10 ? 0 : 1) : ""}</text>
            <text x={x + bw / 2} y={H - B + 12} textAnchor="middle" fontSize="9" fill="var(--muted)">{i + 1}.</text>
          </g>);
      })}
      <text x={(L + W - R) / 2} y={H - 4} textAnchor="middle" fontSize="9" fill="var(--muted)">den v měsíci</text>
    </svg>
  );
}

export function EvPanel({ locId, mod, onClose }) {
  const { has } = useAuth();
  const [live, setLive] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [daily, setDaily] = useState([]);
  const [month, setMonth] = useState(() => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}`; });
  const load = () => {
    api.evState(locId).then((r) => setLive(r.state)).catch(() => {});
    api.evSessionsMonth(locId, month).then(setSessions).catch(() => {});
    api.evDailyMonth(locId, month).then(setDaily).catch(() => {});
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

        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
          <b style={{ fontSize: 13 }}>Nabito po dnech</b>
          <button className="btn" style={{ padding: "1px 8px" }} onClick={() => shiftMonth(-1)} title="předchozí měsíc">◀</button>
          <span style={{ fontSize: 13, minWidth: 120, textAlign: "center" }}>{monthLabel}</span>
          <button className="btn" style={{ padding: "1px 8px" }} onClick={() => shiftMonth(1)} title="další měsíc">▶</button>
          <span className="muted" style={{ fontSize: 11.5 }}>světlý sloupec = celkem za den (kWh) · tenké sloupečky od nuly = jednotlivé relace</span>
        </div>
        <MonthChart month={month} daily={daily} sessions={sessions} />

        <b style={{ fontSize: 13 }}>Historie relací</b>
        {sessions.length ? (
          <table style={{ fontSize: 12, marginTop: 6, width: "100%" }}>
            <thead><tr><th>Od</th><th>Do</th><th>Nabíjení</th><th>kWh</th><th>max kW</th><th>fáze</th><th>ze sítě</th><th>z FVE</th><th>Kč</th><th>konec</th></tr></thead>
            <tbody>{sessions.map((s) => (
              <tr key={s.id}>
                <td>{dt(s.started_at)}</td><td>{s.ended_at ? dt(s.ended_at) : <b style={{ color: "var(--green)" }}>probíhá</b>}</td>
                <td>{dur(s.charging_s || 0)}</td><td><b>{(((s.wh ?? s.wh_max) || 0) / 1000).toFixed(1)}</b></td>
                <td>{((s.max_power_w || 0) / 1000).toFixed(1)}</td><td>{s.phases || "—"}</td>
                <td>{(s.grid_kwh || 0).toFixed(1)}</td><td>{(s.pv_kwh || 0).toFixed(1)}</td><td>{(s.cost_czk || 0).toFixed(0)}</td>
                <td className="muted">{{ unplugged: "odpojeno", complete: "nabito", error: "chyba", orphan: "ztraceno" }[s.ended_reason] || ""}</td>
              </tr>))}
            </tbody></table>
        ) : <p className="muted" style={{ fontSize: 12 }}>Zatím žádná relace (začne připojením auta).</p>}
        <p className="muted" style={{ fontSize: 11, marginTop: 8 }}>ze sítě / z FVE = rozdělení podle okamžitého importu lokality během nabíjení; Kč = síťová část × efektivní cena importu z ceníku.</p>
      </div>
    </div>
  );
}
