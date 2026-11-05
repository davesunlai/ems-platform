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
    api.btCurrent(locId).then((c) => { setCur(c); if (c && sel && sel.id === c.id) setSel(null); }).catch(() => {});
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
      <div onClick={(e) => e.stopPropagation()} className="panel" style={{ width: "98vw", maxWidth: "none", maxHeight: "96vh", overflow: "auto", padding: 14 }}>
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
    <div style={{ marginTop: 8, fontSize: 14 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <b style={{ fontSize: 16 }}>Test #{t.id}</b> <span>{PHASE[t.status] || t.status}</span>
        <span className="muted">start {dt(t.started_at)}{t.ended_at ? ` · konec ${dt(t.ended_at)}` : ""}</span>
        {t.abort_reason && <span style={{ color: "#f85149" }}>{t.abort_reason}</span>}
        {running && onAbort && <button className="btn" style={{ marginLeft: "auto", borderColor: "#f85149" }} disabled={busy} onClick={onAbort}>⛔ Přerušit test</button>}
        {onClose && <button className="btn" style={{ marginLeft: "auto", padding: "1px 8px" }} onClick={onClose}>✕</button>}
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
        nabíjení {t.params?.p_chg_kw} kW · vybíjení {t.params?.p_dis_kw} kW · výdrž {t.params?.hold_min} min · {t.params?.floor_pct}–{t.params?.ceil_pct} % · jmenovitě {t.params?.capacity_kwh} kWh
      </div>
      {t.live && (
        <div style={{ margin: "6px 0", display: "flex", gap: 16, flexWrap: "wrap" }}>
          <Stat l="SoC teď" v={`${t.live.soc != null ? Math.round(t.live.soc) : "?"} %`} big />
          <Stat l="výkon baterie" v={`${t.live.bat_w != null ? (t.live.bat_w / 1000).toFixed(1) : "?"} kW`} />
          <Stat l="ve fázi" v={`${t.live.phase_elapsed_min} min`} />
          <Stat l="nabito ve fázi" v={`${t.live.e_phase_chg_kwh} kWh`} /><Stat l="vybito ve fázi" v={`${t.live.e_phase_dis_kwh} kWh`} />
          <Stat l="síť" v={`${t.live.grid_w != null ? (t.live.grid_w / 1000).toFixed(1) : "?"} kW`} />
        </div>)}
      <TestChart t={t} />
      <StepBars t={t} />
      {t.result && (
        <div style={{ margin: "8px 0", display: "flex", gap: 16, flexWrap: "wrap" }}>
          <Stat l="nabito 10→100" v={`${r.e_charge_kwh ?? "—"} kWh`} /><Stat l="dokap při výdrži" v={`${r.e_hold_kwh ?? "—"} kWh`} />
          <Stat l="vybito 100→10" v={`${r.e_discharge_kwh ?? "—"} kWh`} /><Stat l="kapacita (0–100)" v={`${r.capacity_est_kwh ?? "—"} kWh`} big />
          <Stat l="kondice SoH" v={`${r.soh_pct ?? "—"} %`} big /><Stat l="účinnost" v={`${r.efficiency_pct ?? "—"} %`} />
          {r.pack_drift_pct_max != null && <Stat l="max rozdíl packů" v={`${r.pack_drift_pct_max} %`} />}
        </div>)}
      {snaps.length > 0 && (
        <table style={{ fontSize: 13, width: "100%", marginTop: 6 }}>
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

// Graf průběhu: výkon baterie (zelená = nabíjení, červená = vybíjení) + SoC (modrá, pravá osa) + stínování fází + značky snímků
function TestChart({ t }) {
  const ser = t.series || [];
  if (ser.length < 2) return <p className="muted" style={{ fontSize: 12 }}>Graf se vykreslí po prvních minutách dat.</p>;
  const W = 1400, H = 300, L = 54, R = 52, T = 18, B = 32, F = 13;
  const t0 = new Date(t.started_at).getTime(); const t1 = new Date(ser[ser.length - 1].ts).getTime() + 60000;
  const span = Math.max(1, t1 - t0);
  const maxKw = Math.max(2, ...ser.map((p) => Math.abs((p.bat_w || 0) / 1000)));
  const top = Math.ceil(maxKw / 2) * 2;
  const xs = (ts) => L + (W - L - R) * ((new Date(ts).getTime() - t0) / span);
  const yk = (kw) => T + (H - T - B) * (1 - (kw + top) / (2 * top));
  const ys = (s) => T + (H - T - B) * (1 - s / 100);
  const y0 = yk(0);
  const area = ser.map((p, i) => `${i ? "L" : "M"}${xs(p.ts).toFixed(1)},${yk((p.bat_w || 0) / 1000).toFixed(1)}`).join(" ");
  const socPath = ser.filter((p) => p.soc != null).map((p, i) => `${i ? "L" : "M"}${xs(p.ts).toFixed(1)},${ys(p.soc).toFixed(1)}`).join(" ");
  const marks = t.phase_marks || [];
  const PH = { discharge0: ["#f8514922", "fáze 0 ⬇"], charge: ["#3fb95022", "fáze 1 ⬆"], hold: ["#d2992222", "fáze 2 ⏸"], discharge: ["#f8514922", "fáze 3 ⬇"] };
  const tm = (ts) => new Date(ts).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  const stepMs = span < 2 * 3600000 ? 600000 : span < 6 * 3600000 ? 1800000 : span < 30 * 3600000 ? 3600000 : 7200000;
  const ticks = []; for (let x = Math.ceil(t0 / stepMs) * stepMs; x < t1; x += stepMs) ticks.push(x);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", marginTop: 6 }}>
      {marks.map((m, i) => { const a = xs(m.ts), b = i + 1 < marks.length ? xs(marks[i + 1].ts) : W - R; return (
        <g key={i}><rect x={a} y={T} width={Math.max(0, b - a)} height={H - T - B} fill={PH[m.phase]?.[0] || "transparent"} />
          <text x={a + 5} y={T + 13} fontSize={F} fill="var(--muted)">{PH[m.phase]?.[1]}</text></g>); })}
      {[-top, -top / 2, 0, top / 2, top].map((v) => (
        <g key={v}><line x1={L} x2={W - R} y1={yk(v)} y2={yk(v)} stroke="var(--border)" strokeWidth={v === 0 ? 1.2 : 0.6} />
          <text x={L - 5} y={yk(v) + 4} textAnchor="end" fontSize={F} fill="var(--muted)">{v > 0 ? "+" : ""}{v}</text></g>))}
      <text x={4} y={T + 2} fontSize={F} fill="var(--muted)">kW</text>
      {[0, 25, 50, 75, 100].map((v) => <text key={v} x={W - R + 5} y={ys(v) + 4} fontSize={F} fill="#58a6ff">{v} %</text>)}
      {ticks.map((x) => <g key={x}><line x1={xs(x)} x2={xs(x)} y1={T} y2={H - B + 5} stroke="var(--border)" strokeWidth="0.6" />
        <text x={xs(x)} y={H - B + 19} textAnchor="middle" fontSize={F} fill="var(--muted)">{tm(x)}</text></g>)}
      <path d={`${area} L${xs(ser[ser.length - 1].ts).toFixed(1)},${y0} L${xs(ser[0].ts).toFixed(1)},${y0} Z`} fill="var(--green)" opacity="0.15" />
      <path d={area} fill="none" stroke="var(--green)" strokeWidth="1.4" />
      {socPath && <path d={socPath} fill="none" stroke="#58a6ff" strokeWidth="1.6" strokeDasharray="4 3" />}
      {(t.snapshots || []).filter((s) => s.phase !== "hold").map((s) => (
        <g key={s.id}><line x1={xs(s.ts)} x2={xs(s.ts)} y1={T} y2={H - B} stroke="var(--fg)" strokeWidth="0.6" strokeDasharray="2 3" opacity="0.6" />
          <text x={xs(s.ts)} y={H - B - 5} textAnchor="middle" fontSize={F} fontWeight="600" fill="var(--fg)">{s.soc_step} %</text></g>))}
    </svg>
  );
}

// Sloupce kWh po 10 % (⬆ nabíjení zelené, ⬇ vybíjení červené) s časem úseku
function StepBars({ t }) {
  const snaps = (t.snapshots || []).filter((s) => (s.phase === "charge" || s.phase === "discharge") && s.e_step_kwh != null && s.minutes_step > 0.5);
  if (!snaps.length) return null;
  const nominal = Number(t.params?.capacity_kwh || 0) / 10;
  const W = 1400, H = 190, L = 46, T = 18, B = 40; const n = snaps.length; const bw = Math.min(80, (W - L - 10) / n - 8);
  const maxV = Math.max(nominal || 0, ...snaps.map((s) => Number(s.e_step_kwh)));
  const y = (v) => T + (H - T - B) * (1 - v / maxV);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", marginTop: 4 }}>
      {nominal > 0 && <g><line x1={L} x2={W - 10} y1={y(nominal)} y2={y(nominal)} stroke="var(--amber)" strokeDasharray="4 3" />
        <text x={W - 12} y={y(nominal) - 4} textAnchor="end" fontSize="13" fill="var(--amber)">jmenovitě {nominal.toFixed(2)} kWh / 10 %</text></g>}
      <text x={4} y={T + 2} fontSize="13" fill="var(--muted)">kWh</text>
      {snaps.map((s, i) => { const x = L + 6 + i * ((W - L - 10) / n); const v = Number(s.e_step_kwh); const up = s.phase === "charge"; return (
        <g key={s.id}>
          <rect x={x} y={y(v)} width={bw} height={H - B - y(v)} fill={up ? "var(--green)" : "#f85149"} opacity="0.8" rx="3" />
          <text x={x + bw / 2} y={y(v) - 4} textAnchor="middle" fontSize="13" fontWeight="600" fill="var(--fg)">{v.toFixed(2)}</text>
          <text x={x + bw / 2} y={H - B + 15} textAnchor="middle" fontSize="13" fill="var(--fg)">{up ? "⬆" : "⬇"} {s.soc_step} %</text>
          <text x={x + bw / 2} y={H - B + 30} textAnchor="middle" fontSize="12" fill="var(--muted)">{Math.round(s.minutes_step)} min · {(v / (s.minutes_step / 60)).toFixed(1)} kW</text>
        </g>); })}
    </svg>
  );
}

function Stat({ l, v, big }) {
  return <div><div className="muted" style={{ fontSize: 12 }}>{l}</div><div style={{ fontSize: big ? 24 : 18, fontWeight: 700 }}>{v}</div></div>;
}
