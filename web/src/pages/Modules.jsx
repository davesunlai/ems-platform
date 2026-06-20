import { useEffect, useState } from "react";
import { api } from "../api";

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
const DTYPES = ["generation", "storage", "load", "grid_point"];
const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.v, k.l]));

function emptyForm() {
  return { id: "", name: "", adapter: "goodwe", device_type: "storage", kind: "source_read",
           host: "", port: 8899, device_id: 1, battery_pack: 1, pv_peak_w: 16000, battery_capacity_kwh: 52 };
}

export default function Modules() {
  const [mods, setMods] = useState([]);
  const [err, setErr] = useState("");
  const [f, setF] = useState(emptyForm());

  const load = () => api.listModules().then(setMods).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const buildParams = () => {
    if (f.adapter === "goodwe") return { host: f.host, port: Number(f.port) };
    if (f.adapter === "solis") return { host: f.host, port: Number(f.port), device_id: Number(f.device_id), battery_pack: Number(f.battery_pack) };
    if (f.adapter === "mock") return { pv_peak_w: Number(f.pv_peak_w), battery_capacity_kwh: Number(f.battery_capacity_kwh) };
    return {};
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
        <h3>Nový modul</h3>
        <div className="row">
          <div className="field" style={{ marginBottom: 0 }}>
            <label>ID</label>
            <input value={f.id} placeholder="home-fve-hybrid" onChange={(e) => setF({ ...f, id: e.target.value })} />
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
            <select value={f.adapter} onChange={(e) => { const a = e.target.value; setF({ ...f, adapter: a, port: a === "solis" ? 502 : a === "goodwe" ? 8899 : f.port }); }}>
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
            <div className="field" style={{ marginBottom: 0 }}>
              <label>Baterie (pack)</label>
              <select value={f.battery_pack} onChange={(e) => setF({ ...f, battery_pack: e.target.value })}>
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </div>
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
          <button className="btn primary" onClick={create} disabled={!f.id.trim()}>Přidat modul</button>
        </div>
        <p className="error">{err}</p>
      </div>

      <div className="panel">
        <h3>Moduly</h3>
        <table>
          <thead><tr><th>ID</th><th>Název</th><th>Typ</th><th>Adaptér</th><th>Zařízení</th><th>Parametry</th><th>Stav</th><th></th></tr></thead>
          <tbody>
            {mods.map((m) => (
              <tr key={m.id}>
                <td>{m.id}</td>
                <td className="muted">{m.name}</td>
                <td style={{ fontSize: 12 }}>{KIND_LABEL[m.kind] || m.kind}</td>
                <td className="role">{m.adapter}</td>
                <td className="muted">{m.device_type}</td>
                <td className="muted" style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
                  {m.params.host ? `${m.params.host}:${m.params.port}` : JSON.stringify(m.params)}
                </td>
                <td><span className={m.enabled ? "badge-on" : "badge-off"}>{m.enabled ? "zapnutý" : "vypnutý"}</span></td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
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
