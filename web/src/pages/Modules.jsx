import { useEffect, useState } from "react";
import { api } from "../api";
import Icon from "../components/Icon";
import { MAX_TRACKED, METRIC_LABEL, iconFor, groupMetrics, metricsFor, controlFor } from "../metrics";

const ADAPTERS = ["goodwe", "solis", "mock"];
const ADAPTER_LABEL = {
  goodwe: "Goodwe — FVE + baterie (UDP/Modbus)",
  solis: "Solis S6-EH3P50K-H — FVE + baterie (Modbus TCP)",
  mock: "Mock — simulace (bez HW)",
};
const KINDS = [
  { v: "source_read", l: "Čtecí (telemetrie)" },
  { v: "source_write", l: "Zápisový (řízení) — fáze C" },
  { v: "logic", l: "Logika (automatizace) — fáze D" },
];
const DTYPES = ["hybrid", "generation", "storage", "load", "grid_point", "sensor"];
const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.v, k.l]));

function emptyForm() {
  return { id: "", name: "", adapter: "goodwe", device_type: "storage", kind: "source_read",
           host: "", port: 8899, device_id: 1, battery_pack: 1, battery_packs: "auto", hidden: [], control: [], pv_peak_w: 16000, battery_capacity_kwh: 52 };
}

export default function Modules() {
  const [mods, setMods] = useState([]);
  const [err, setErr] = useState("");
  const [f, setF] = useState(emptyForm());
  const [editing, setEditing] = useState(null);   // id editovaného modulu, nebo null
  const [avail, setAvail] = useState([]);          // metriky, které modul reálně posílá

  const load = () => api.listModules().then(setMods).catch((e) => setErr(e.message));
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, []);

  const buildParams = () => {
    let p = {};
    if (f.adapter === "goodwe") p = { host: f.host, port: Number(f.port) };
    else if (f.adapter === "solis") {
      p = { host: f.host, port: Number(f.port), device_id: Number(f.device_id) };
      if (f.device_type === "hybrid") p.battery_packs = f.battery_packs;
      else if (f.device_type === "storage") p.battery_pack = Number(f.battery_pack);
    }
    else if (f.adapter === "mock") p = { pv_peak_w: Number(f.pv_peak_w), battery_capacity_kwh: Number(f.battery_capacity_kwh) };
    if (f.hidden && f.hidden.length) p.hidden_metrics = f.hidden;
    if (f.control && f.control.length) p.control_enabled = f.control;
    return p;
  };

  const toggleMetric = (k) => setF((s) => {
    if (s.hidden.includes(k)) {
      // zapínáme (odebíráme ze skrytých) -> hlídej limit
      const shown = metricsFor(s.adapter, s.device_type, avail);
      const checked = shown.filter((m) => !s.hidden.includes(m)).length;
      if (checked >= MAX_TRACKED) return s;   // přes limit nepovolíme
      return { ...s, hidden: s.hidden.filter((x) => x !== k) };
    }
    return { ...s, hidden: [...s.hidden, k] };
  });

  const toggleControl = (k) => setF((s) => ({
    ...s,
    control: s.control.includes(k) ? s.control.filter((x) => x !== k) : [...s.control, k],
  }));

  const startEdit = (m) => {
    const p = m.params || {};
    setEditing(m.id);
    setErr("");
    setAvail([]);
    api.latest(m.id).then((l) => setAvail(Object.keys(l.metrics || {}))).catch(() => setAvail([]));
    setF({
      id: m.id, name: m.name || "", adapter: m.adapter, device_type: m.device_type, kind: m.kind,
      host: p.host || "", port: p.port ?? (m.adapter === "solis" ? 502 : 8899),
      device_id: p.device_id ?? 1, battery_pack: p.battery_pack ?? 1, battery_packs: p.battery_packs ?? "auto",
      hidden: p.hidden_metrics ?? [],
      control: p.control_enabled ?? [],
      pv_peak_w: p.pv_peak_w ?? 16000, battery_capacity_kwh: p.battery_capacity_kwh ?? 52,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const cancelEdit = () => { setEditing(null); setAvail([]); setF(emptyForm()); setErr(""); };
  const save = async () => {
    setErr("");
    try {
      await api.updateModule(editing, {
        name: f.name, adapter: f.adapter, device_type: f.device_type,
        kind: f.kind, params: buildParams(),
      });
      setEditing(null); setF(emptyForm()); load();
    } catch (e) { setErr(e.message); }
  };

  const create = async () => {
    setErr("");
    try {
      await api.createModule({
        id: f.id, name: f.name, adapter: f.adapter, device_type: f.device_type,
        kind: f.kind, params: buildParams(), enabled: true,
      });
      setF(emptyForm()); load();
    } catch (e) { setErr(e.message); }
  };
  const toggle = async (m) => { try { await api.updateModule(m.id, { enabled: !m.enabled }); load(); } catch (e) { setErr(e.message); } };
  const remove = async (id) => { if (!confirm(`Smazat modul ${id}?`)) return; try { await api.deleteModule(id); load(); } catch (e) { setErr(e.message); } };

  return (
    <main>
      <div className="panel" style={{ marginBottom: 22 }}>
        <h3>{editing ? `Upravit modul „${editing}"` : "Nový modul"}</h3>
        <div className="row">
          <div className="field" style={{ marginBottom: 0 }}>
            <label>ID</label>
            <input value={f.id} placeholder="home-fve-hybrid" disabled={!!editing}
                   onChange={(e) => setF({ ...f, id: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Název</label>
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Typ modulu</label>
            <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              {KINDS.map((k) => <option key={k.v} value={k.v}>{k.l}</option>)}
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Adaptér</label>
            <select value={f.adapter} onChange={(e) => { const a = e.target.value; setF({ ...f, adapter: a, port: a === "solis" ? 502 : a === "goodwe" ? 8899 : f.port, device_type: a === "solis" ? "hybrid" : f.device_type }); }}>
              {ADAPTERS.map((a) => <option key={a} value={a}>{ADAPTER_LABEL[a] || a}</option>)}
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Typ zařízení</label>
            <select value={f.device_type} onChange={(e) => setF({ ...f, device_type: e.target.value })}>
              {DTYPES.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
        </div>

        <div className="row" style={{ marginTop: 12 }}>
          {f.adapter === "goodwe" && (<>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>IP měniče (host)</label>
              <input value={f.host} placeholder="192.168.6.172" onChange={(e) => setF({ ...f, host: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Port</label>
              <input value={f.port} onChange={(e) => setF({ ...f, port: e.target.value })} />
            </div>
          </>)}
          {f.adapter === "solis" && (<>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>IP měniče (host)</label>
              <input value={f.host} placeholder="192.168.6.180" onChange={(e) => setF({ ...f, host: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Port</label>
              <input value={f.port} onChange={(e) => setF({ ...f, port: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Modbus device_id</label>
              <input value={f.device_id} onChange={(e) => setF({ ...f, device_id: e.target.value })} />
            </div>
            {f.device_type === "storage" && (
              <div className="field" style={{ marginBottom: 0 }}>
                <label>Baterie (pack)</label>
                <select value={f.battery_pack} onChange={(e) => setF({ ...f, battery_pack: e.target.value })}>
                  <option value={1}>1</option>
                  <option value={2}>2</option>
                </select>
              </div>
            )}
            {f.device_type === "hybrid" && (
              <div className="field" style={{ marginBottom: 0 }}>
                <label>Počet baterií</label>
                <select value={f.battery_packs} onChange={(e) => setF({ ...f, battery_packs: e.target.value })}>
                  <option value="auto">Auto (najde se)</option>
                  <option value="1">1</option>
                  <option value="2">2</option>
                </select>
              </div>
            )}
          </>)}
          {f.adapter === "mock" && (<>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>FVE špička (W)</label>
              <input value={f.pv_peak_w} onChange={(e) => setF({ ...f, pv_peak_w: e.target.value })} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Kapacita baterie (kWh)</label>
              <input value={f.battery_capacity_kwh} onChange={(e) => setF({ ...f, battery_capacity_kwh: e.target.value })} />
            </div>
          </>)}
          {editing && (() => {
            const shown = metricsFor(f.adapter, f.device_type, avail);
            const checked = shown.filter((k) => !f.hidden.includes(k)).length;
            const groups = groupMetrics(shown);
            return (
              <div className="field" style={{ marginBottom: 8 }}>
                <label>
                  Co sledovat (zobrazovat) ·{" "}
                  <span style={{ color: checked > MAX_TRACKED ? "#e06c75" : "inherit" }}>vybráno {checked}/{MAX_TRACKED}</span>
                  {checked > MAX_TRACKED && <span style={{ color: "#e06c75", fontWeight: 400 }}> — přes limit o {checked - MAX_TRACKED} (příplatek)</span>}
                </label>
                {shown.length === 0 ? (
                  <p className="muted" style={{ fontSize: 12, margin: 0 }}>
                    Načítám měřené veličiny — modul je musí nejdřív aspoň jednou změřit (~10 s).
                  </p>
                ) : (<>
                  {groups.map((g) => (
                    <div key={g.id} style={{ marginTop: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, opacity: 0.75, margin: "2px 0 4px" }}>
                        <Icon name={g.icon} size={14} /> {g.label}
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "6px 14px" }}>
                        {g.items.map((k) => {
                          const on = !f.hidden.includes(k);
                          const blocked = !on && checked >= MAX_TRACKED;
                          return (
                            <label key={k} title={blocked ? `Limit ${MAX_TRACKED} veličin — odeber jinou nebo přikup příplatek` : ""}
                                   style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 400,
                                            cursor: blocked ? "not-allowed" : "pointer", opacity: blocked ? 0.45 : 1 }}>
                              <input type="checkbox" checked={on} disabled={blocked} onChange={() => toggleMetric(k)} />
                              <Icon name={iconFor(k)} size={15} style={{ opacity: 0.7 }} />
                              {METRIC_LABEL[k] || k}
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                  <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                    Sledování až <strong>{MAX_TRACKED}</strong> veličin je v základu. Další veličiny nad rámec {MAX_TRACKED} jsou za příplatek — ozvi se nám.
                  </p>
                </>)}
              </div>
            );
          })()}
          {editing && (() => {
            const ctrl = controlFor(f.adapter, f.device_type);
            if (!ctrl.length) return null;
            return (
              <div className="field" style={{ marginBottom: 8 }}>
                <label>Ovládání a konfigurace</label>
                <p className="muted" style={{ fontSize: 12, margin: "0 0 4px" }}>
                  Co půjde u modulu řídit a nastavovat. Zápisová (řídicí) vrstva je zatím{" "}
                  <strong>příprava — fáze C</strong>; volby se uloží a aktivují se, jakmile řízení spustíme.
                </p>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "6px 14px", marginTop: 4 }}>
                  {ctrl.map((c) => (
                    <label key={c.key} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 400, cursor: "pointer" }}>
                      <input type="checkbox" checked={f.control.includes(c.key)} onChange={() => toggleControl(c.key)} />
                      <Icon name={c.icon} size={15} style={{ opacity: 0.7 }} />
                      {c.label}
                    </label>
                  ))}
                </div>
              </div>
            );
          })()}
          {editing ? (<>
            <button className="btn primary" onClick={save}>Uložit změny</button>
            <button className="btn" onClick={cancelEdit} style={{ marginLeft: 8 }}>Zrušit</button>
          </>) : (
            <button className="btn primary" onClick={create} disabled={!f.id.trim()}>Přidat modul</button>
          )}
        </div>
        <p className="error">{err}</p>
      </div>

      <div className="panel">
        <h3>Moduly</h3>
        <table>
          <thead><tr><th></th><th>ID</th><th>Název</th><th>Typ</th><th>Adaptér</th><th>Zařízení</th><th>Lokalita</th><th>Parametry</th><th>Stav</th><th></th></tr></thead>
          <tbody>
            {mods.map((m) => (
              <tr key={m.id}>
                <td style={{ width: 18, textAlign: "center" }}>
                  <span title={m.active ? "aktivní — čerstvá data" : "neaktivní — žádná čerstvá data"}
                        style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%",
                                 background: m.active ? "var(--green)" : "#e06c75" }} />
                </td>
                <td>{m.id}</td>
                <td className="muted">{m.name}</td>
                <td style={{ fontSize: 12 }}>{KIND_LABEL[m.kind] || m.kind}</td>
                <td className="role">{m.adapter}</td>
                <td className="muted">{m.device_type}</td>
                <td className="muted">{m.locality || "—"}</td>
                <td className="muted" style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
                  {m.params.host ? `${m.params.host}:${m.params.port}` : JSON.stringify(m.params)}
                </td>
                <td><span className={m.enabled ? "badge-on" : "badge-off"}>{m.enabled ? "zapnutý" : "vypnutý"}</span></td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="btn" onClick={() => startEdit(m)} style={{ marginRight: 8 }}>Upravit</button>
                  <button className="btn" onClick={() => toggle(m)} style={{ marginRight: 8 }}>{m.enabled ? "Vypnout" : "Zapnout"}</button>
                  <button className="btn danger" onClick={() => remove(m.id)}>Smazat</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted" style={{ marginTop: 14, fontSize: 12 }}>
          Změny se projeví do ~10 s — kolektor čte registr živě, bez restartu. Funkční jsou zatím čtecí moduly.
        </p>
      </div>
    </main>
  );
}
