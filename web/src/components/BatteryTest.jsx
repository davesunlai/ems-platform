// 🧪 Test kapacity a kondice baterie — tlačítko (jen s právem ctl:battery_test), dialog s parametry a předkontrolou,
// průběh (fáze, snímky po 10 %), přerušení, výsledek. Backend: /api/battery-test (BATTERY-TEST-BRIEF.md).
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

const FLD = { padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)", width: 90 };
const PHASE = { preparing: "⏳ příprava (čtení nastavení měniče)", discharge0: "⬇ fáze 0 — vybití na dno", charge: "⬆ fáze 1 — nabíjení",
  hold: "⏸ fáze 2 — výdrž na stropu", discharge: "⬇ fáze 3 — vybíjení", done: "✅ dokončen", aborted: "⛔ přerušen" };
const dt = (iso) => (iso ? new Date(iso).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const hrs = (h) => (h == null ? "—" : h >= 1 ? `${h.toFixed(1)} h` : `${Math.round(h * 60)} min`);

export function BatteryTestButton({ locId, compact }) {
  const { has, vis } = useAuth();
  const [open, setOpen] = useState(false);
  const [cur, setCur] = useState(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.btCurrent(locId).then((r) => alive && setCur(r)).catch(() => {});
    load(); const t = setInterval(load, 15000); return () => { alive = false; clearInterval(t); };
  }, [locId]);
  if (!has("control") || !vis("ctl:battery_test")) return null;
  return (<>
    <button className="btn" style={{ padding: compact ? "2px 9px" : "4px 10px", fontSize: 12, borderColor: cur ? "var(--amber)" : undefined }}
            onClick={() => setOpen(true)} title="Reálný test kapacity a kondice baterie (vybít → nabít → výdrž → vybít, snímky po 10 %)">
      🧪 {cur ? `test běží · ${PHASE[cur.status]?.split(" — ")[0] || cur.status}` : "Test baterie"}
    </button>
    {open && <BatteryTestDialog locId={locId} onClose={() => setOpen(false)} />}
  </>);
}

export function BatteryTestDialog({ locId, onClose }) {
  const [defs, setDefs] = useState(null);
  const [mod, setMod] = useState("");
  const [p, setP] = useState(null);
  const [pre, setPre] = useState(null);
  const [cur, setCur] = useState(null);
  const [hist, setHist] = useState([]);
  const [sel, setSel] = useState(null);       // detail historického testu
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [ack, setAck] = useState(false);
  const load = () => {
    api.btCurrent(locId).then(setCur).catch(() => {});
    api.btList(locId).then((r) => setHist(r || [])).catch(() => {});
  };
  useEffect(() => {
    api.btDefaults(locId).then((d) => { setDefs(d); setMod(d.modules?.[0] || ""); setP(d.params); }).catch((e) => setMsg(e.message));
    load(); const t = setInterval(load, 10000); return () => clearInterval(t);
    /* eslint-disable-next-line */ }, [locId]);
  const num = (k) => (e) => setP({ ...p, [k]: e.target.value === "" ? "" : Number(e.target.value) });
  const precheck = async () => {
    setBusy(true); setMsg(""); setPre(null);
    try { setPre(await api.btPrecheck(locId, { module_id: mod, params: p })); setAck(false); } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  const start = async () => {
    if (!window.confirm("Spustit test baterie? Plánovač a ruční řízení budou na tomto modulu zablokované do konce testu.")) return;
    setBusy(true); setMsg("");
    try { await api.btStart(locId, { module_id: mod, params: p, confirmed: true }); setPre(null); load(); } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  const abort = async () => {
    if (!cur || !window.confirm("Přerušit běžící test? Měnič se zastaví, záložní SoC se vrátí, naměřená data zůstanou uložená.")) return;
    setBusy(true); try { await api.btAbort(cur.id); load(); } catch (e) { setMsg(e.message); } setBusy(false);
  };
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 96, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} className="panel" style={{ width: "min(960px, 96vw)", maxHeight: "94vh", overflow: "auto", padding: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <b style={{ fontSize: 15 }}>🧪 Test kapacity a kondice baterie</b>
          <button className="btn" style={{ marginLeft: "auto", padding: "3px 10px" }} onClick={onClose}>✕</button>
        </div>
        {msg && <p style={{ color: "#f85149", fontSize: 12.5 }}>{msg}</p>}

        {cur ? <TestProgress t={cur} onAbort={abort} busy={busy} /> : p && (
          <div style={{ marginTop: 8, fontSize: 13 }}>
            <p className="muted" style={{ margin: "0 0 8px", fontSize: 12.5 }}>
              Cyklus: vybití na dno → nabíjení na strop (snímek po 10 %) → výdrž → vybíjení na dno (snímek po 10 %). Měří se energie na DC straně baterie.
              Výsledek: nabito / vybito kWh, kapacita, účinnost, kondice vs. {p.capacity_kwh} kWh jmenovitých, rozdíl packů.
            </p>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
              {defs?.modules?.length > 1 && <label>modul<br /><select style={{ ...FLD, width: 140 }} value={mod} onChange={(e) => setMod(e.target.value)}>{defs.modules.map((m) => <option key={m}>{m}</option>)}</select></label>}
              <label>nabíjení kW<br /><input style={FLD} type="number" step="0.1" value={p.p_chg_kw} onChange={num("p_chg_kw")} /></label>
              <label>vybíjení kW<br /><input style={FLD} type="number" step="0.1" value={p.p_dis_kw} onChange={num("p_dis_kw")} /></label>
              <label>výdrž na stropu min<br /><input style={FLD} type="number" value={p.hold_min} onChange={num("hold_min")} /></label>
              <label>dno %<br /><input style={FLD} type="number" value={p.floor_pct} onChange={num("floor_pct")} /></label>
              <label>strop %<br /><input style={FLD} type="number" value={p.ceil_pct} onChange={num("ceil_pct")} /></label>
              <label>kapacita kWh<br /><input style={FLD} type="number" step="0.1" value={p.capacity_kwh} onChange={num("capacity_kwh")} /></label>
              <button className="btn" disabled={busy || !mod} onClick={precheck}>🔎 Zkontrolovat a odhadnout</button>
            </div>
            <p className="muted" style={{ fontSize: 11.5, margin: "6px 0 0" }}>Výchozí výkony = 10 % kapacity (0,1 C). Strop exportu distributora má přednost — vybíjení se při slunci ořeže.</p>

            {pre && (
              <div style={{ marginTop: 10, border: "1px solid var(--border)", borderRadius: 8, padding: 10 }}>
                {pre.blockers.map((b, i) => <div key={i} style={{ color: "#f85149" }}>⛔ {b}</div>)}
                {pre.warnings.map((w, i) => <div key={i} style={{ color: "var(--amber)" }}>⚠ {w}</div>)}
                <div style={{ marginTop: 6 }}>
                  SoC teď <b>{pre.soc_now != null ? Math.round(pre.soc_now) : "?"} %</b> · odhad: vybití na dno {hrs(pre.estimate.h_discharge0)} · nabíjení {hrs(pre.estimate.h_charge)} ·
                  výdrž {hrs(pre.estimate.h_hold)} · vybíjení {hrs(pre.estimate.h_discharge)} → <b>celkem ≈ {hrs(pre.estimate.h_total)}</b>
                </div>
                <div style={{ marginTop: 4 }}>🌙 {pre.recommend.msg}</div>
                <div style={{ marginTop: 4 }}>
                  🔌 strop importu při testu = {pre.breaker_phases} × 230 V × {pre.breaker_a ?? "?"} A × 0,95 = <b>{pre.import_limit_kw != null ? `${pre.import_limit_kw} kW` : "— (zadej jistič)"}</b>
                  {" · "}🛡 strop exportu <b>{pre.export_limit_kw ?? "—"} kW</b> (vybíjení = strop − FVE)
                </div>
                {pre.ok && (
                  <div style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "center" }}>
                    <label style={{ fontSize: 12.5 }}><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> Rozumím upozorněním (záložní SoC, wallbox, blokace řízení)</label>
                    <button className="btn primary" disabled={!ack || busy} onClick={start}>▶ Spustit test teď</button>
                  </div>)}
              </div>)}
          </div>)}

        {hist.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <b style={{ fontSize: 13 }}>Historie testů</b>
            <table style={{ fontSize: 12, width: "100%", marginTop: 4 }}>
              <thead><tr><th>#</th><th>Start</th><th>Konec</th><th>Stav</th><th>nabito kWh</th><th>vybito kWh</th><th>kapacita</th><th>SoH</th><th>účinnost</th><th></th></tr></thead>
              <tbody>{hist.map((t) => (
                <tr key={t.id}><td>{t.id}</td><td>{dt(t.started_at)}</td><td>{dt(t.ended_at)}</td><td>{PHASE[t.status]?.split(" — ")[0] || t.status}</td>
                  <td>{t.result?.e_charge_kwh ?? "—"}</td><td>{t.result?.e_discharge_kwh ?? "—"}</td><td>{t.result?.capacity_est_kwh != null ? `${t.result.capacity_est_kwh} kWh` : "—"}</td>
                  <td>{t.result?.soh_pct != null ? `${t.result.soh_pct} %` : "—"}</td><td>{t.result?.efficiency_pct != null ? `${t.result.efficiency_pct} %` : "—"}</td>
                  <td><button className="btn" style={{ padding: "1px 8px" }} onClick={async () => setSel(await api.btGet(t.id))}>detail</button></td></tr>))}
              </tbody></table>
          </div>)}
        {sel && <div style={{ marginTop: 10 }}><TestProgress t={sel} onClose={() => setSel(null)} /></div>}
      </div>
    </div>
  );
}

export function TestProgress({ t, onAbort, busy, onClose }) {
  const running = ["preparing", "discharge0", "charge", "hold", "discharge"].includes(t.status);
  const snaps = (t.snapshots || []).filter((s) => s.phase === "charge" || s.phase === "discharge");
  const r = t.result || {};
  return (
    <div style={{ marginTop: 8, fontSize: 13 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <b>Test #{t.id}</b> <span>{PHASE[t.status] || t.status}</span>
        <span className="muted">start {dt(t.started_at)}{t.ended_at ? ` · konec ${dt(t.ended_at)}` : ""}</span>
        {t.abort_reason && <span style={{ color: "#f85149" }}>{t.abort_reason}</span>}
        {running && onAbort && <button className="btn" style={{ marginLeft: "auto", borderColor: "#f85149" }} disabled={busy} onClick={onAbort}>⛔ Přerušit test</button>}
        {onClose && <button className="btn" style={{ marginLeft: "auto", padding: "1px 8px" }} onClick={onClose}>✕</button>}
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
        nabíjení {t.params?.p_chg_kw} kW · vybíjení {t.params?.p_dis_kw} kW · výdrž {t.params?.hold_min} min · {t.params?.floor_pct}–{t.params?.ceil_pct} % · jmenovitě {t.params?.capacity_kwh} kWh
      </div>
      {t.result && (
        <div style={{ margin: "8px 0", display: "flex", gap: 16, flexWrap: "wrap" }}>
          <Stat l="nabito 10→100" v={`${r.e_charge_kwh ?? "—"} kWh`} /><Stat l="dokap při výdrži" v={`${r.e_hold_kwh ?? "—"} kWh`} />
          <Stat l="vybito 100→10" v={`${r.e_discharge_kwh ?? "—"} kWh`} /><Stat l="kapacita (0–100)" v={`${r.capacity_est_kwh ?? "—"} kWh`} big />
          <Stat l="kondice SoH" v={`${r.soh_pct ?? "—"} %`} big /><Stat l="účinnost" v={`${r.efficiency_pct ?? "—"} %`} />
          {r.pack_drift_pct_max != null && <Stat l="max rozdíl packů" v={`${r.pack_drift_pct_max} %`} />}
        </div>)}
      {snaps.length > 0 && (
        <table style={{ fontSize: 12, width: "100%", marginTop: 6 }}>
          <thead><tr><th>fáze</th><th>SoC</th><th>čas</th><th>kWh od začátku fáze</th><th>+kWh / 10 %</th><th>min</th><th>⌀ kW</th><th>pack 1 / 2</th><th>článek min/max V</th><th>síť kW</th></tr></thead>
          <tbody>{snaps.map((s) => (
            <tr key={s.id}><td>{s.phase === "charge" ? "⬆" : "⬇"}</td><td><b>{s.soc_step} %</b></td><td>{dt(s.ts)}</td><td>{Number(s.e_phase_kwh).toFixed(2)}</td>
              <td>{s.e_step_kwh != null ? Number(s.e_step_kwh).toFixed(2) : "—"}</td><td>{s.minutes_step != null ? Math.round(s.minutes_step) : "—"}</td>
              <td>{s.e_step_kwh && s.minutes_step ? (Number(s.e_step_kwh) / (Number(s.minutes_step) / 60)).toFixed(2) : "—"}</td>
              <td>{s.soc1 != null ? `${Math.round(s.soc1)} / ${Math.round(s.soc2)} %` : "—"}</td>
              <td>{s.cell_vmin != null ? `${Number(s.cell_vmin).toFixed(3)} / ${Number(s.cell_vmax).toFixed(3)}` : "—"}</td>
              <td>{s.grid_w != null ? (Number(s.grid_w) / 1000).toFixed(1) : "—"}</td></tr>))}
          </tbody></table>)}
      {t.log?.length > 0 && (
        <details style={{ marginTop: 8 }}><summary className="muted" style={{ cursor: "pointer", fontSize: 12 }}>protokol ({t.log.length})</summary>
          <div style={{ fontSize: 11.5, maxHeight: 220, overflow: "auto", marginTop: 4 }}>{t.log.map((l, i) => (
            <div key={i} style={{ color: l.level === "warn" ? "var(--amber)" : undefined }}><span className="muted">{dt(l.ts)}</span> {l.msg}</div>))}</div>
        </details>)}
    </div>
  );
}

function Stat({ l, v, big }) {
  return <div><div className="muted" style={{ fontSize: 11 }}>{l}</div><div style={{ fontSize: big ? 20 : 15, fontWeight: 700 }}>{v}</div></div>;
}
