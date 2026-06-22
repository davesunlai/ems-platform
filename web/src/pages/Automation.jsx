import { useEffect, useState } from "react";
import { api } from "../api";
import SpotCurve from "../components/SpotCurve";

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

const empty = { id: "", kind: "spot_charge", target_module: "", price_threshold: 1500, soc: 90, soc_start: 50, power: 100 };

export default function Automation() {
  const [rules, setRules] = useState([]);
  const [mods, setMods] = useState([]);
  const [f, setF] = useState(empty);
  const [editing, setEditing] = useState(null);
  const [err, setErr] = useState("");
  const [spot, setSpot] = useState(null);
  const [controlled, setControlled] = useState([]);

  const load = () => api.listRules().then(setRules).catch((e) => setErr(e.message));
  const loadSpot = () => api.spot().then(setSpot).catch(() => {});
  const loadCtrl = () => api.plannerControlled().then((r) => setControlled(r.devices || [])).catch(() => {});
  useEffect(() => {
    load();
    api.controlModules().then((m) => { setMods(m); setF((x) => ({ ...x, target_module: m[0]?.id || "" })); }).catch(() => {});
    loadSpot(); loadCtrl();
    const t = setInterval(() => { load(); loadSpot(); loadCtrl(); }, 8000);
    return () => clearInterval(t);
  }, []);

  const buildParams = () => {
    const isCharge = f.kind === "spot_charge";
    return isCharge
      ? { target_module: f.target_module, price_threshold: Number(f.price_threshold), soc_start: Number(f.soc_start), soc_max: Number(f.soc), charge_power: Number(f.power) }
      : { target_module: f.target_module, price_threshold: Number(f.price_threshold), soc_min: Number(f.soc), discharge_power: Number(f.power) };
  };

  const reset = () => { setEditing(null); setF({ ...empty, target_module: mods[0]?.id || "" }); };

  const save = async () => {
    setErr("");
    try {
      if (editing) {
        await api.updateRule(editing, { params: buildParams() });
      } else {
        await api.createRule({ id: f.id, type: f.kind, enabled: true, params: buildParams() });
      }
      reset(); load();
    } catch (e) { setErr(e.message); }
  };

  const edit = (r) => {
    const isCharge = r.type === "spot_charge";
    setEditing(r.id);
    setF({
      id: r.id, kind: r.type, target_module: r.params.target_module,
      price_threshold: r.params.price_threshold,
      soc: isCharge ? (r.params.soc_max ?? 90) : (r.params.soc_min ?? 20),
      soc_start: r.params.soc_start ?? 100,
      power: isCharge ? (r.params.charge_power ?? 100) : (r.params.discharge_power ?? 100),
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const toggle = async (r) => { try { await api.updateRule(r.id, { enabled: !r.enabled }); load(); } catch (e) { setErr(e.message); } };
  const remove = async (id) => { if (!confirm(`Smazat pravidlo ${id}?`)) return; try { await api.deleteRule(id); if (editing === id) reset(); load(); } catch (e) { setErr(e.message); } };

  const isCharge = f.kind === "spot_charge";

  return (
    <main>
      <SpotPanel onChange={() => { load(); loadSpot(); }} />

      <div className="panel" style={{ marginBottom: 18 }}>
        <h3>Cenová křivka (15min, OTE)</h3>
        <SpotCurve rules={rules} />
      </div>

      <div className="panel" style={{ marginBottom: 18 }}>
        <h3>{editing ? `Upravit pravidlo: ${editing}` : "Nové pravidlo"}</h3>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Typ</label>
            <select value={f.kind} disabled={!!editing} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              <option value="spot_charge">Nabíjet při nízké ceně</option>
              <option value="spot_discharge">Vybíjet do sítě při vysoké ceně</option>
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>ID</label>
            <input value={f.id} disabled={!!editing} placeholder={isCharge ? "levne-nabijeni" : "drahe-vybijeni"} onChange={(e) => setF({ ...f, id: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Cílový měnič</label>
            <select value={f.target_module} onChange={(e) => setF({ ...f, target_module: e.target.value })}>
              {mods.map((m) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)}
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>{isCharge ? "Práh (nabíjet pod, Kč)" : "Práh (vybíjet nad, Kč)"}</label>
            <input value={f.price_threshold} onChange={(e) => setF({ ...f, price_threshold: e.target.value })} style={{ width: 150 }} />
          </div>
          {isCharge && (
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Začít nabíjet pod SoC (%)</label>
              <input value={f.soc_start} onChange={(e) => setF({ ...f, soc_start: e.target.value })} style={{ width: 110 }} />
            </div>
          )}
          <div className="field" style={{ marginBottom: 0 }}>
            <label>{isCharge ? "Nabít do SoC (%)" : "Min SoC (%)"}</label>
            <input value={f.soc} onChange={(e) => setF({ ...f, soc: e.target.value })} style={{ width: 110 }} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Výkon (%)</label>
            <input value={f.power} onChange={(e) => setF({ ...f, power: e.target.value })} style={{ width: 90 }} />
          </div>
          <button className="btn primary" onClick={save} disabled={!f.id.trim() || !f.target_module}>{editing ? "Uložit změny" : "Přidat"}</button>
          {editing && <button className="btn" onClick={reset}>Zrušit</button>}
        </div>
        <p className="error">{err}</p>
        <p className="muted" style={{ fontSize: 12 }}>
          {isCharge
            ? "Nabíjení s hysterezí: spustí se, jen když cena klesne pod práh a SoC je pod hodnotou „začít nabíjet pod“. Pak nabíjí dál až po „nabít do SoC“ a teprve potom přejde do normálu — díky tomu to neskáče sem a tam. Pro tvůj případ: začít pod 50, nabít do 100."
            : "Vybíjení do sítě: když je cena nad prahem a SoC nad minimem → vybíjení do sítě; jinak normál. Min SoC chrání baterii."}
        </p>
      </div>

      <div className="panel">
        <h3>Pravidla</h3>
        <table>
          <thead><tr><th>ID</th><th>Typ</th><th>Cíl</th><th>Práh</th><th>SoC</th><th>Stav</th><th>Poslední rozhodnutí</th><th>Poslední akce</th><th></th></tr></thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>{r.type === "spot_charge" ? "🔋 nabíjení" : "⚡ vybíjení"}</td>
                <td className="role">
                  {r.params.target_module}
                  {controlled.includes(r.params.target_module) && (
                    <span style={{ marginLeft: 6, background: "var(--amber, #d29922)", color: "#1a1a1a", padding: "1px 8px", borderRadius: 10, fontSize: 11, fontWeight: 700, whiteSpace: "nowrap" }}>
                      ⚠ přebírá plánovač
                    </span>
                  )}
                </td>
                <td className="muted">{r.type === "spot_charge" ? "< " : "> "}{r.params.price_threshold} Kč</td>
                <td className="muted">
                  {r.type === "spot_charge"
                    ? `${r.params.soc_start != null && r.params.soc_start < 100 ? `pod ${r.params.soc_start} → ` : ""}do ${r.params.soc_max} %`
                    : `≥ ${r.params.soc_min} %`}
                </td>
                <td><span className={r.enabled ? "badge-on" : "badge-off"}>{r.enabled ? "zapnuto" : "vypnuto"}</span></td>
                <td className="muted" style={{ fontSize: 12 }}>{r.last_decision || "—"}</td>
                <td className="muted" style={{ fontSize: 12 }}>
                  {r.last_action ? `${r.last_action}` : "—"}
                  {r.last_action_at ? ` (${new Date(r.last_action_at).toLocaleTimeString("cs-CZ")})` : ""}
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="btn" onClick={() => edit(r)} style={{ marginRight: 8 }}>Upravit</button>
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
