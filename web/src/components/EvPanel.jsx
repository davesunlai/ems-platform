// 🚗 Wallbox — panel po kliknutí na uzel ve schématu (Dashboard) a karta v Ovládání (sdílené).
// Živý stav, historie relací, kWh po dnech; řízení jen s právem control; nastavení modulu jen admin.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

export const EV_CAR = { idle: "bez auta", charging: "⚡ nabíjí", wait_car: "auto připojeno, čeká", complete: "✅ nabito", error: "⛔ chyba", unknown: "?" };
const FLD = { padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };
const dt = (iso) => (iso ? new Date(iso).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const dur = (s) => (s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min` : `${Math.round(s / 60)} min`);

// Řízení (cíl EMS = proud / fáze / start-stop; uvolnit = frc=0)
export function EvControl({ mod, live, onSent }) {
  const { has } = useAuth();
  const [st, setSt] = useState(null);
  const [amp, setAmp] = useState(16);
  const [psm, setPsm] = useState(2);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const refresh = () => api.controlStates(mod.id).then((r) => setSt((r?.states || {})[mod.id] || null)).catch(() => {});
  useEffect(() => { refresh(); const t = setInterval(refresh, 10000); return () => clearInterval(t); /* eslint-disable-next-line */ }, [mod.id]);
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
          <label style={{ fontSize: 12 }}>proud <input style={{ ...FLD, width: 56 }} value={amp} onChange={(e) => setAmp(e.target.value)} /> A</label>
          <select style={FLD} value={psm} onChange={(e) => setPsm(Number(e.target.value))}>
            <option value={1}>1 fáze</option><option value={2}>3 fáze</option><option value={0}>auto</option>
          </select>
          <span className="muted" style={{ fontSize: 12 }}>≈ {estKw(Number(amp) || 0, psm)} kW</span>
          <button className="btn primary" disabled={busy} onClick={() => send("ev_set", { amp: Number(amp), psm, frc: 2 }, `nabíjet ${amp} A ${psm === 1 ? "1f" : psm === 2 ? "3f" : "auto"}`)}>⚡ Nabíjet</button>
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
export function EvPanel({ locId, mod, onClose }) {
  const { has } = useAuth();
  const [live, setLive] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [daily, setDaily] = useState([]);
  const load = () => {
    api.evState(locId).then((r) => setLive(r.state)).catch(() => {});
    api.evSessions(locId, 30).then(setSessions).catch(() => {});
    api.evDaily(locId, 14).then(setDaily).catch(() => {});
  };
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); /* eslint-disable-next-line */ }, [locId]);
  const kw = live?.power_w != null ? (live.power_w / 1000).toFixed(1) : "?";
  const maxDay = Math.max(0.1, ...daily.map((x) => x.kwh || 0));
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 95, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} className="panel" style={{ width: "min(760px, 96%)", maxHeight: "92vh", overflow: "auto", padding: 14 }}>
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

        <b style={{ fontSize: 13 }}>Nabito po dnech (14 dní)</b>
        {daily.length ? (
          <div style={{ display: "flex", gap: 4, alignItems: "flex-end", height: 70, margin: "6px 0 10px" }}>
            {daily.map((x) => (
              <div key={x.day} title={`${new Date(x.day).toLocaleDateString("cs-CZ")}: ${x.kwh} kWh · max ${x.max_power_kw} kW`} style={{ flex: 1, textAlign: "center", fontSize: 10 }}>
                <div style={{ height: Math.max(2, 50 * (x.kwh || 0) / maxDay), background: "var(--green)", borderRadius: 3, opacity: x.kwh ? 0.9 : 0.25 }} />
                <div className="muted">{new Date(x.day).getDate()}.</div>
                <div>{x.kwh ? x.kwh.toFixed(0) : ""}</div>
              </div>))}
          </div>
        ) : <p className="muted" style={{ fontSize: 12 }}>Zatím bez denních dat (agregát se plní po hodině).</p>}

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
