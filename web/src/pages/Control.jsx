import { useEffect, useState } from "react";
import { api } from "../api";

function ModuleControl({ mod, onCommand }) {
  const [mode, setMode] = useState(null);
  const [power, setPower] = useState(100);
  const [soc, setSoc] = useState(100);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const refreshMode = () => api.getMode(mod.id).then((r) => setMode(r.mode)).catch(() => setMode("?"));
  useEffect(() => { refreshMode(); }, [mod.id]);

  const send = async (body, label) => {
    if (!confirm(`Opravdu odeslat povel „${label}" do měniče ${mod.id}?`)) return;
    setBusy(true); setMsg("");
    try {
      const r = await api.setBatteryMode(mod.id, body);
      setMsg(`✓ ${r.message}`);
      refreshMode(); onCommand();
    } catch (e) { setMsg(`✗ ${e.message}`); }
    finally { setBusy(false); }
  };

  return (
    <div className="panel" style={{ marginBottom: 18 }}>
      <h3>{mod.name || mod.id}</h3>
      <p className="muted" style={{ marginTop: -8 }}>
        Aktuální režim: <span className="role">{mode ?? "…"}</span>
        <button className="btn" style={{ marginLeft: 10, padding: "3px 9px" }} onClick={refreshMode}>obnovit</button>
      </p>
      <div className="row" style={{ marginTop: 8 }}>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Výkon nabíjení (%)</label>
          <input value={power} onChange={(e) => setPower(e.target.value)} style={{ width: 120 }} />
        </div>
        <div className="field" style={{ marginBottom: 0 }}>
          <label>SoC cíl/podlaha (%)</label>
          <input value={soc} onChange={(e) => setSoc(e.target.value)} style={{ width: 120 }} />
        </div>
        <button className="btn primary" disabled={busy}
                onClick={() => send({ mode: "force_charge", power_pct: Number(power), target_soc: Number(soc) }, "Vynutit nabíjení")}>
          Vynutit nabíjení
        </button>
        <button className="btn" disabled={busy}
                onClick={() => send({ mode: "force_discharge", power_pct: Number(power), target_soc: Number(soc) }, "Vynutit vybíjení do sítě")}>
          Vynutit vybíjení do sítě
        </button>
        <button className="btn" disabled={busy}
                onClick={() => send({ mode: "normal" }, "Normální režim")}>
          Normální režim (self-use)
        </button>
      </div>
      {msg && <p className={msg.startsWith("✓") ? "" : "error"} style={{ marginTop: 10 }}>{msg}</p>}
    </div>
  );
}

export default function Control() {
  const [mods, setMods] = useState(null);
  const [audit, setAudit] = useState([]);
  const [err, setErr] = useState("");

  const loadAudit = () => api.controlAudit().then(setAudit).catch(() => {});
  useEffect(() => {
    api.controlModules().then(setMods).catch((e) => setErr(e.message));
    loadAudit();
  }, []);

  if (err) return <main><div className="panel"><p className="error">{err}</p></div></main>;
  if (!mods) return <main><p className="muted">Načítám…</p></main>;

  return (
    <main>
      <div className="panel" style={{ marginBottom: 18, borderColor: "var(--amber)" }}>
        <p className="muted" style={{ margin: 0 }}>
          ⚠ Tyto akce <b>reálně zapisují do měniče</b>. Vynucené nabíjení čerpá výkon do baterie až do cílového SoC;
          „Normální režim" vrátí běžné self-use chování. Každý povel se ověřuje čtením a zaznamenává do auditu.
        </p>
      </div>

      {mods.length === 0 && <p className="muted">Žádný řiditelný modul (goodwe).</p>}
      {mods.map((m) => <ModuleControl key={m.id} mod={m} onCommand={loadAudit} />)}

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
                <td><span className={a.ok ? "badge-on" : "badge-off"}>{a.ok ? "OK" : "chyba"}</span>
                    {a.result?.confirmed_mode ? ` → ${a.result.confirmed_mode}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
