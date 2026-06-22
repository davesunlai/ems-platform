import { useEffect, useState } from "react";
import { api } from "../api";

// Mezipaměť načtených řídicích registrů per modul (v rámci session SPA),
// ať se při každém otevření Řízení nečte znovu ze střídače.
const ctrlCache = {};

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
  const applyControls = (c) => {
    if (c["43012"] != null) setChA(c["43012"] / 10);
    if (c["43013"] != null) setDisA(c["43013"] / 10);
    if (c["43024"] != null) setSocBackup(c["43024"]);
    if (c["43030"] != null) setSocForce(c["43030"]);
  };
  const readNow = async () => {
    setBusy(true);
    const res = await runCommand(mod.id, "read_controls", {}, setStatus, "Načtení stavu");
    setBusy(false);
    const c = res?.controls;
    if (c) {
      applyControls(c);
      const at = new Date();
      ctrlCache[mod.id] = { c, at };
      setStatus({ state: "done", text: `✓ Načtení stavu provedeno ${at.toLocaleString("cs-CZ")}` });
    }
  };

  // Po otevření: použij mezipaměť (do 15 min), jinak čti z měniče. Ať se nečte při každém otevření.
  useEffect(() => {
    const hit = ctrlCache[mod.id];
    if (hit && Date.now() - hit.at.getTime() < 15 * 60 * 1000) {
      applyControls(hit.c);
      setStatus({ state: "done", text: `Z mezipaměti (z měniče načteno ${hit.at.toLocaleString("cs-CZ")})` });
    } else {
      readNow();
    }
    /* eslint-disable-line */
  }, [mod.id]);

  const fld = { width: 110, padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h3 style={{ marginBottom: 2 }}>{mod.id} <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· Solis</span></h3>
      <p className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
        ⚠️ Reálně zapisuje do měniče. Force výkon je <b>syrová hodnota registru</b> (scale u 3f neověřen) — začni nízko.
      </p>

      <div style={{ fontWeight: 600, fontSize: 13, margin: "8px 0 4px" }}>Ruční řízení</div>
      <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 12 }}>výkon <span className="muted">(syrová hodnota registru)</span> <input value={power} onChange={(e) => setPower(e.target.value)} style={{ ...fld, width: 90 }} /></label>
        {has("force_charge") && <button className="btn" disabled={busy} onClick={() => force("force_charge", `Nabíjet teď (${power})`)}>⚡ Nabíjet teď</button>}
        {has("force_discharge") && <button className="btn" disabled={busy} onClick={() => force("force_discharge", `Vybíjet teď (${power})`)}>🔻 Vybíjet teď</button>}
        <button className="btn" disabled={busy} style={{ color: "#e06c75" }} onClick={stop}>⏹ Stop</button>
      </div>

      <div style={{ fontWeight: 600, fontSize: 13, margin: "14px 0 6px", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span>Limity a režim</span>
        <button className="btn primary" style={{ padding: "8px 18px", fontSize: 14, fontWeight: 700 }} disabled={busy} onClick={readNow}>
          ⟳ Načíst aktuální z měniče
        </button>
        {busy && <span className="muted" style={{ fontSize: 12 }}>čtu z měniče…</span>}
        <span className="muted" style={{ fontSize: 11, fontWeight: 400 }}>(hodnoty jsou živé z měniče, ne z databáze)</span>
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

const ACT_LABEL = {
  charge_pv: "nabíjení z FVE", charge_grid: "nabíjení ze sítě", discharge_load: "vybíjení do domu",
  discharge_grid: "vybíjení do sítě", export: "přetok do sítě", import: "odběr ze sítě", idle: "klid",
};

function PlannerPanel({ locId }) {
  const [data, setData] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const reload = () => api.getPlanner(locId).then((r) => { setData(r); setCfg({ ...r.config }); }).catch(() => {});
  useEffect(() => { if (locId) reload(); }, [locId]);
  if (!locId || !cfg) return null;

  const set = (k, v) => setCfg({ ...cfg, [k]: v });
  const NUM = ["capacity_kwh", "soc_min_pct", "outage_reserve_pct", "max_charge_kw", "max_discharge_kw", "horizon_h"];
  const save = async () => {
    setBusy(true); setMsg("");
    const payload = { ...cfg };
    for (const k of NUM) payload[k] = cfg[k] === "" || cfg[k] == null ? null : Number(cfg[k]);
    try { await api.setPlannerConfig(locId, payload); setMsg("Uloženo a přepočítáno."); reload(); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const cur = data?.current;
  const sched = data?.schedule || [];
  const fld = { width: 90, padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };
  const planImp = sched.reduce((s, r) => s + (r.import_kwh || 0), 0);
  const planExp = sched.reduce((s, r) => s + (r.export_kwh || 0), 0);

  return (
    <div className="panel" style={{ marginBottom: 14, borderColor: cfg.enabled ? "var(--green)" : "var(--border)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 700, fontSize: 14 }}>🧠 Plánovač lokality</span>
        <label style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 13, fontWeight: 600, color: cfg.enabled ? "var(--green)" : "var(--muted)" }}>
          <input type="checkbox" checked={!!cfg.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          {cfg.enabled ? "ZAPNUTÝ — řídí měnič" : "vypnutý (jen plán)"}
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12 }}>
          <input type="checkbox" checked={!!cfg.allow_grid_discharge} onChange={(e) => set("allow_grid_discharge", e.target.checked)} />
          povolit vybíjení do sítě
        </label>
      </div>
      {cfg.enabled && (
        <p className="muted" style={{ fontSize: 11.5, margin: "6px 0 0", color: "var(--amber)" }}>
          ⚠ Zapnutý plánovač <b>reálně řídí měnič</b> (přes frontu, na nastavených limitech proudu) a přebírá řízení místo reaktivních spot pravidel této lokality.
          {cfg.allow_grid_discharge ? " Vybíjení do sítě je povolené — 43136 neověřen, sleduj výkon." : ""}
        </p>
      )}

      <div className="row" style={{ gap: 12, flexWrap: "wrap", marginTop: 10 }}>
        <div><label style={{ fontSize: 12, display: "block" }}>Kapacita (kWh)</label><input style={fld} value={cfg.capacity_kwh ?? ""} onChange={(e) => set("capacity_kwh", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>SoC min (%)</label><input style={fld} value={cfg.soc_min_pct ?? ""} onChange={(e) => set("soc_min_pct", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>Rezerva výpadek (%)</label><input style={fld} value={cfg.outage_reserve_pct ?? ""} onChange={(e) => set("outage_reserve_pct", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>Max nabíjení (kW)</label><input style={fld} value={cfg.max_charge_kw ?? ""} onChange={(e) => set("max_charge_kw", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>Max vybíjení (kW)</label><input style={fld} value={cfg.max_discharge_kw ?? ""} onChange={(e) => set("max_discharge_kw", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>Horizont (h)</label><input style={fld} value={cfg.horizon_h ?? ""} onChange={(e) => set("horizon_h", e.target.value)} /></div>
        <button className="btn primary" style={{ alignSelf: "flex-end", padding: "8px 16px" }} disabled={busy} onClick={save}>Uložit a přepočítat</button>
      </div>

      <div style={{ marginTop: 10, fontSize: 13 }}>
        {cur
          ? <span>Teď: <b>{ACT_LABEL[cur.action] || cur.action}</b> · SoC plán {Math.round(cur.soc_pct)} % <span className="muted">— {cur.reason}</span></span>
          : <span className="muted">Zatím bez plánu — potřebuje predikci výroby (zadej polohu/panely a dej Přepočítat predikci).</span>}
        {sched.length > 0 && <span className="muted"> · plán {sched.length} h, odběr {planImp.toFixed(1)} kWh, přetok {planExp.toFixed(1)} kWh</span>}
      </div>
      {msg && <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>{msg}</p>}
    </div>
  );
}

function LocalitySection({ locId, locName, mods }) {
  return (
    <section style={{ marginBottom: 24 }}>
      <h2 style={{ fontSize: 17, margin: "0 0 8px" }}>📍 {locName || "Bez lokality"}</h2>
      {locId && <PlannerPanel locId={locId} />}
      {mods.map((m) => m.adapter === "solis"
        ? <SolisControl key={m.id} mod={m} />
        : <GoodweControl key={m.id} mod={m} />)}
    </section>
  );
}

function HelpPanel() {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginBottom: 14 }}>
      <button className="btn" style={{ padding: "8px 16px", fontWeight: 600 }} onClick={() => setOpen(!open)}>
        {open ? "▲ Skrýt nápovědu" : "❓ Nápověda — co umí Řízení"}
      </button>
      {open && (
        <div className="panel" style={{ marginTop: 8, lineHeight: 1.55 }}>
          <p style={{ marginTop: 0 }}><b>Co je Řízení?</b> Tady se rozhoduje, jak se má baterie a měnič chovat. Dashboard jen ukazuje stav; tady do něj zasahuješ. Vše je seskupené <b>podle lokality</b> a u každé lokality jsou její <b>moduly (měniče)</b>.</p>
          <p><b>🧠 Plánovač lokality</b> — „mozek", který se sám rozhodne, kdy nabíjet a kdy vybíjet, aby ušetřil. Dívá se na předpověď výroby z FVE, na spotřebu domu a na ceny elektřiny, a podle toho:</p>
          <ul style={{ marginTop: 0 }}>
            <li>nabije baterii, když je elektřina <b>nejlevnější</b> (a počítá s tím, kolik dodá FVE),</li>
            <li>schová energii na <b>večerní špičku</b> (případně ji prodá do sítě, pokud to povolíš),</li>
            <li>vždy nechá <b>rezervu</b> pro případ výpadku sítě.</li>
          </ul>
          <p style={{ marginTop: 0 }}>Dokud je <b>vypnutý</b>, jen ukazuje plán (fialová křivka SoC v grafu na dashboardu) a nic nedělá. Když ho <b>zapneš</b>, začne měnič reálně řídit a <b>přebere řízení</b> místo jednotlivých spotových pravidel.</p>
          <p><b>🔌 Ruční řízení</b> — okamžitý zásah: „Nabíjet teď / Vybíjet teď / Stop". Hodí se na vyzkoušení nebo když chceš mít kontrolu sám. Plánovač i automatika tím jdou stranou, dokud nedáš Stop.</p>
          <p><b>⚙️ Limity a režim</b> — bezpečnostní mantinely měniče: maximální nabíjecí/vybíjecí proud a hranice nabití (SoC), pod kterou se baterie nevybíjí. „Načíst aktuální z měniče" ukáže, co měnič právě má nastaveno.</p>
          <p style={{ marginBottom: 0 }}><b>Bezpečnost:</b> každý povel se reálně zapíše do měniče, ověří zpětným čtením a zapíše do <b>auditu</b> dole. Když si nejsi jistý, začni nízkými hodnotami.</p>
        </div>
      )}
    </div>
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
    (byLoc[key] = byLoc[key] || { id: m.locality_id ?? null, name: m.locality, mods: [] }).mods.push(m);
  }
  const groups = Object.values(byLoc);

  return (
    <main>
      <HelpPanel />
      <div className="panel" style={{ marginBottom: 18, borderColor: "var(--amber)" }}>
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          ⚠ Akce zde <b>reálně zapisují do měniče</b> (přes frontu, ověřeno čtením, zaznamenáno do auditu).
          Aktuální vynucený stav vidíš i na dashboardu jako zvýrazněný pruh.
        </p>
      </div>

      {mods.length === 0 && <p className="muted">Žádný řiditelný modul.</p>}
      {groups.map((g, i) => <LocalitySection key={i} locId={g.id} locName={g.name} mods={g.mods} />)}

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
