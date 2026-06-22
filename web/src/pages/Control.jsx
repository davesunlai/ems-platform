import { useEffect, useState } from "react";
import { api } from "../api";

// Zařadí povel do fronty a počká na provedení kolektorem.
async function runCommand(moduleId, action, params, setStatus, label) {
  setStatus({ state: "pending", text: `Odesílám: ${label}…` });
  try {
    const { id: cmdId } = await api.enqueueCommand(moduleId, action, params);
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const c = await api.commandStatus(cmdId);
      if (c.status === "done") { setStatus({ state: "done", text: `✓ ${label} provedeno` }); return c.result; }
      if (c.status === "error") { setStatus({ state: "error", text: `✗ ${label}: ${c.result?.error || "chyba"}` }); return null; }
      setStatus({ state: "pending", text: `Čekám na kolektor (#${cmdId})…` });
    }
  } catch (e) { setStatus({ state: "error", text: `✗ ${e.message || e}` }); }
  return null;
}

function StatusLine({ status }) {
  if (!status) return null;
  const c = status.state === "error" ? "#e06c75" : status.state === "done" ? "var(--green)" : "var(--muted)";
  return <p style={{ marginTop: 8, fontSize: 13, color: c }}>{status.text}</p>;
}

function SolisControl({ mod }) {
  const has = (k) => (mod.control_enabled || []).includes(k);
  const [power, setPower] = useState(1000);
  const [chA, setChA] = useState("");
  const [disA, setDisA] = useState("");
  const [socBackup, setSocBackup] = useState("");
  const [socForce, setSocForce] = useState("");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  const ask = (msg) => window.confirm(msg);

  const force = async (action, label) => {
    if (!ask(`Opravdu poslat do měniče ${mod.id}: ${label}?`)) return;
    setBusy(true); await runCommand(mod.id, action, { power: Number(power) }, setStatus, label); setBusy(false);
  };
  const stop = async () => {
    if (!ask(`Vrátit měnič ${mod.id} do normálu (Self-Use)?`)) return;
    setBusy(true); await runCommand(mod.id, "stop", {}, setStatus, "Stop (normál)"); setBusy(false);
  };
  const setLimit = async (action, params, label) => {
    if (!ask(`Opravdu nastavit ${label} na měniči ${mod.id}?`)) return;
    setBusy(true); await runCommand(mod.id, action, params, setStatus, label); setBusy(false);
  };
  const readNow = async () => {
    setBusy(true);
    const res = await runCommand(mod.id, "read_controls", {}, setStatus, "Načtení stavu");
    setBusy(false);
    const c = res?.controls;
    if (c) {
      if (c["43012"] != null) setChA(c["43012"] / 10);
      if (c["43013"] != null) setDisA(c["43013"] / 10);
      if (c["43024"] != null) setSocBackup(c["43024"]);
      if (c["43030"] != null) setSocForce(c["43030"]);
    }
  };

  const fld = { width: 110, padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h3 style={{ marginBottom: 2 }}>{mod.id} <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· Solis</span></h3>
      <p className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
        ⚠️ Reálně zapisuje do měniče. Force výkon je <b>syrová hodnota registru</b> (scale u 3f neověřen) — začni nízko.
      </p>

      <div style={{ fontWeight: 600, fontSize: 13, margin: "8px 0 4px" }}>Ruční řízení</div>
      <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 12 }}>výkon <input value={power} onChange={(e) => setPower(e.target.value)} style={{ ...fld, width: 90 }} /></label>
        {has("force_charge") && <button className="btn" disabled={busy} onClick={() => force("force_charge", `Nabíjet teď (${power})`)}>⚡ Nabíjet teď</button>}
        {has("force_discharge") && <button className="btn" disabled={busy} onClick={() => force("force_discharge", `Vybíjet teď (${power})`)}>🔻 Vybíjet teď</button>}
        <button className="btn" disabled={busy} style={{ color: "#e06c75" }} onClick={stop}>⏹ Stop</button>
      </div>

      <div style={{ fontWeight: 600, fontSize: 13, margin: "12px 0 4px" }}>
        Limity a režim <button className="btn" style={{ padding: "2px 9px", marginLeft: 6 }} disabled={busy} onClick={readNow}>Načíst aktuální</button>
      </div>
      <div className="row" style={{ gap: 14, flexWrap: "wrap" }}>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Nabíjecí proud (A)</label>
          <input value={chA} onChange={(e) => setChA(e.target.value)} style={fld} />
          <button className="btn" style={{ padding: "3px 9px", marginLeft: 4 }} disabled={busy || chA === ""}
                  onClick={() => setLimit("set_charge_current", { amps: Number(chA) }, `nabíjecí proud ${chA} A`)}>Uložit</button>
        </div>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Vybíjecí proud (A)</label>
          <input value={disA} onChange={(e) => setDisA(e.target.value)} style={fld} />
          <button className="btn" style={{ padding: "3px 9px", marginLeft: 4 }} disabled={busy || disA === ""}
                  onClick={() => setLimit("set_discharge_current", { amps: Number(disA) }, `vybíjecí proud ${disA} A`)}>Uložit</button>
        </div>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Záložní SoC (%)</label>
          <input value={socBackup} onChange={(e) => setSocBackup(e.target.value)} style={fld} />
          <button className="btn" style={{ padding: "3px 9px", marginLeft: 4 }} disabled={busy || socBackup === ""}
                  onClick={() => setLimit("set_soc_backup", { pct: Number(socBackup) }, `záložní SoC ${socBackup} %`)}>Uložit</button>
        </div>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Force SoC (%)</label>
          <input value={socForce} onChange={(e) => setSocForce(e.target.value)} style={fld} />
          <button className="btn" style={{ padding: "3px 9px", marginLeft: 4 }} disabled={busy || socForce === ""}
                  onClick={() => setLimit("set_soc_force", { pct: Number(socForce) }, `force SoC ${socForce} %`)}>Uložit</button>
        </div>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Pracovní režim</label>
          <button className="btn" disabled={busy} onClick={() => setLimit("set_work_mode", { word: 33 }, "režim Self-Use")}>Self-Use</button>
        </div>
      </div>
      <StatusLine status={status} />
    </div>
  );
}

function GoodweControl({ mod }) {
  const [mode, setMode] = useState(null);
  const [power, setPower] = useState(100);
  const [soc, setSoc] = useState(100);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () => api.getMode(mod.id).then((r) => setMode(r.mode)).catch(() => setMode("?"));
  useEffect(() => { refresh(); }, [mod.id]);

  const send = async (body, label) => {
    if (!window.confirm(`Opravdu odeslat „${label}" do měniče ${mod.id}?`)) return;
    setBusy(true); setMsg("");
    try { const r = await api.setBatteryMode(mod.id, body); setMsg(`✓ ${r.message}`); refresh(); }
    catch (e) { setMsg(`✗ ${e.message}`); } finally { setBusy(false); }
  };
  const fld = { width: 110, padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h3 style={{ marginBottom: 2 }}>{mod.id} <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· goodwe · režim {mode ?? "…"}</span></h3>
      <div className="row" style={{ gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginTop: 6 }}>
        <label style={{ fontSize: 12 }}>Výkon (%)<input value={power} onChange={(e) => setPower(e.target.value)} style={fld} /></label>
        <label style={{ fontSize: 12 }}>SoC cíl (%)<input value={soc} onChange={(e) => setSoc(e.target.value)} style={fld} /></label>
        <button className="btn primary" disabled={busy} onClick={() => send({ mode: "force_charge", power_pct: Number(power), target_soc: Number(soc) }, "Vynutit nabíjení")}>⚡ Nabíjet</button>
        <button className="btn" disabled={busy} onClick={() => send({ mode: "force_discharge", power_pct: Number(power), target_soc: Number(soc) }, "Vynutit vybíjení")}>🔻 Vybíjet</button>
        <button className="btn" disabled={busy} onClick={() => send({ mode: "normal" }, "Normální režim")}>⏹ Normál</button>
      </div>
      {msg && <p style={{ marginTop: 8, fontSize: 13, color: msg.startsWith("✓") ? "var(--green)" : "#e06c75" }}>{msg}</p>}
    </div>
  );
}

function LocalitySection({ locName, mods }) {
  return (
    <section style={{ marginBottom: 24 }}>
      <h2 style={{ fontSize: 17, margin: "0 0 4px" }}>📍 {locName || "Bez lokality"}</h2>
      <div className="panel" style={{ marginBottom: 14, borderColor: "var(--border)", background: "color-mix(in srgb, var(--accent, #58a6ff) 5%, transparent)" }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>Plánovač lokality</div>
        <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>
          Prediktivní řízení (nabíjení v nejlevnějším spotu, vybíjení ve špičce, rezerva pro výpadek) — připravujeme v dalším kroku.
        </p>
      </div>
      {mods.map((m) => m.adapter === "solis"
        ? <SolisControl key={m.id} mod={m} />
        : <GoodweControl key={m.id} mod={m} />)}
    </section>
  );
}

export default function Control() {
  const [mods, setMods] = useState(null);
  const [audit, setAudit] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.controlModules().then(setMods).catch((e) => setErr(e.message));
    api.controlAudit().then(setAudit).catch(() => {});
  }, []);

  if (err) return <main><div className="panel"><p className="error">{err}</p></div></main>;
  if (!mods) return <main><p className="muted">Načítám…</p></main>;

  // seskupení podle lokality
  const byLoc = {};
  for (const m of mods) {
    const key = m.locality_id ?? "none";
    (byLoc[key] = byLoc[key] || { name: m.locality, mods: [] }).mods.push(m);
  }
  const groups = Object.values(byLoc);

  return (
    <main>
      <div className="panel" style={{ marginBottom: 18, borderColor: "var(--amber)" }}>
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          ⚠ Akce zde <b>reálně zapisují do měniče</b> (přes frontu, ověřeno čtením, zaznamenáno do auditu).
          Aktuální vynucený stav vidíš i na dashboardu jako zvýrazněný pruh.
        </p>
      </div>

      {mods.length === 0 && <p className="muted">Žádný řiditelný modul.</p>}
      {groups.map((g, i) => <LocalitySection key={i} locName={g.name} mods={g.mods} />)}

      <div className="panel">
        <h3>Audit povelů</h3>
        <table>
          <thead><tr><th>Čas</th><th>Uživatel</th><th>Modul</th><th>Akce</th><th>Parametry</th><th>Výsledek</th></tr></thead>
          <tbody>
            {audit.map((a) => (
              <tr key={a.id}>
                <td className="muted" style={{ fontSize: 12 }}>{new Date(a.time).toLocaleString("cs-CZ")}</td>
                <td>{a.username}</td>
                <td className="role">{a.module_id}</td>
                <td>{a.action}</td>
                <td className="muted" style={{ fontSize: 12, fontFamily: "var(--mono)" }}>{JSON.stringify(a.params)}</td>
                <td><span className={a.ok ? "badge-on" : "badge-off"}>{a.ok ? "OK" : "chyba"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
