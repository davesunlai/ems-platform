import { useEffect, useState } from "react";
import { api } from "../api";

function SpotPanel({ onChange }) {
  const [st, setSt] = useState(null);
  const [manual, setManual] = useState("");
  const load = () => api.spot().then(setSt).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);

  const setM = async () => { await api.setManualPrice(Number(manual)); setManual(""); load(); onChange && onChange(); };
  const clr = async () => { await api.clearManualPrice(); load(); onChange && onChange(); };

  return (
    <div className="panel" style={{ marginBottom: 18 }}>
      <h3>Spotová cena (trh OTE)</h3>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 12 }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 30, fontWeight: 600 }}>
          {st?.price != null ? Math.round(st.price) : "—"}
          <span className="unit" style={{ fontSize: 15, color: "var(--muted)", marginLeft: 6 }}>{st?.currency || "CZK/MWh"}</span>
        </span>
        {st?.manual && <span className="role" style={{ color: "var(--amber)", borderColor: "var(--amber)" }}>RUČNÍ TEST</span>}
      </div>
      <div className="row">
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Ruční cena (test)</label>
          <input value={manual} placeholder="např. 800" onChange={(e) => setManual(e.target.value)} style={{ width: 140 }} />
        </div>
        <button className="btn" onClick={setM} disabled={!manual}>Nastavit ručně</button>
        <button className="btn" onClick={clr} disabled={!st?.manual}>Zpět na živý feed</button>
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
        Ruční cena slouží k otestování pravidel bez čekání na trh. „Zpět na živý feed" obnoví automatické načítání z OTE.
      </p>
    </div>
  );
}

const empty = { id: "", target_module: "", price_threshold: 1500, soc_max: 90, charge_power: 100 };

export default function Automation() {
  const [rules, setRules] = useState([]);
  const [mods, setMods] = useState([]);
  const [f, setF] = useState(empty);
  const [err, setErr] = useState("");

  const load = () => api.listRules().then(setRules).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.controlModules().then((m) => { setMods(m); setF((x) => ({ ...x, target_module: m[0]?.id || "" })); }).catch(() => {});
    const t = setInterval(load, 8000); return () => clearInterval(t);
  }, []);

  const create = async () => {
    setErr("");
    try {
      await api.createRule({
        id: f.id, type: "spot_charge", enabled: true,
        params: { target_module: f.target_module, price_threshold: Number(f.price_threshold),
                  soc_max: Number(f.soc_max), charge_power: Number(f.charge_power) },
      });
      setF({ ...empty, target_module: mods[0]?.id || "" }); load();
    } catch (e) { setErr(e.message); }
  };
  const toggle = async (r) => { try { await api.updateRule(r.id, { enabled: !r.enabled }); load(); } catch (e) { setErr(e.message); } };
  const remove = async (id) => { if (!confirm(`Smazat pravidlo ${id}?`)) return; try { await api.deleteRule(id); load(); } catch (e) { setErr(e.message); } };

  return (
    <main>
      <SpotPanel onChange={load} />

      <div className="panel" style={{ marginBottom: 18 }}>
        <h3>Nové pravidlo — nabíjení dle spotové ceny</h3>
        <div className="row">
          <div className="field" style={{ marginBottom: 0 }}>
            <label>ID</label>
            <input value={f.id} placeholder="levne-nabijeni" onChange={(e) => setF({ ...f, id: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Cílový měnič</label>
            <select value={f.target_module} onChange={(e) => setF({ ...f, target_module: e.target.value })}>
              {mods.map((m) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)}
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Práh ceny (Kč/MWh)</label>
            <input value={f.price_threshold} onChange={(e) => setF({ ...f, price_threshold: e.target.value })} style={{ width: 120 }} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Max SoC (%)</label>
            <input value={f.soc_max} onChange={(e) => setF({ ...f, soc_max: e.target.value })} style={{ width: 90 }} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Výkon (%)</label>
            <input value={f.charge_power} onChange={(e) => setF({ ...f, charge_power: e.target.value })} style={{ width: 90 }} />
          </div>
          <button className="btn primary" onClick={create} disabled={!f.id.trim() || !f.target_module}>Přidat</button>
        </div>
        <p className="error">{err}</p>
        <p className="muted" style={{ fontSize: 12 }}>
          Logika: když je spotová cena pod prahem a SoC pod maximem → vynucené nabíjení; jinak normální režim.
        </p>
      </div>

      <div className="panel">
        <h3>Pravidla</h3>
        <table>
          <thead><tr><th>ID</th><th>Cíl</th><th>Práh</th><th>Max SoC</th><th>Stav</th><th>Poslední rozhodnutí</th><th>Poslední akce</th><th></th></tr></thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td className="role">{r.params.target_module}</td>
                <td className="muted">{r.params.price_threshold} Kč</td>
                <td className="muted">{r.params.soc_max} %</td>
                <td><span className={r.enabled ? "badge-on" : "badge-off"}>{r.enabled ? "zapnuto" : "vypnuto"}</span></td>
                <td className="muted" style={{ fontSize: 12 }}>{r.last_decision || "—"}</td>
                <td className="muted" style={{ fontSize: 12 }}>
                  {r.last_action ? `${r.last_action}` : "—"}
                  {r.last_action_at ? ` (${new Date(r.last_action_at).toLocaleTimeString("cs-CZ")})` : ""}
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="btn" onClick={() => toggle(r)} style={{ marginRight: 8 }}>{r.enabled ? "Vypnout" : "Zapnout"}</button>
                  <button className="btn danger" onClick={() => remove(r.id)}>Smazat</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
