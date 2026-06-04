import { useEffect, useState } from "react";
import { api } from "../api";

const lbl = { display: "flex", flexDirection: "column", gap: 4, fontSize: 13 };

function ContactRow({ mod, cfg, onChange }) {
  const [f, setF] = useState({
    enabled: cfg?.enabled || false,
    upper_soc: cfg?.upper_soc ?? 100,
    lower_soc: cfg?.lower_soc ?? 95,
  });
  const [msg, setMsg] = useState("");

  const upd = (k) => (e) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const save = async () => {
    setMsg("");
    if (Number(f.lower_soc) >= Number(f.upper_soc)) { setMsg("Dolní mez musí být nižší než horní"); return; }
    try {
      await api.setContact(mod.id, {
        enabled: f.enabled, upper_soc: Number(f.upper_soc), lower_soc: Number(f.lower_soc),
      });
      setMsg("Uloženo ✓"); onChange && onChange();
    } catch (e) { setMsg("Chyba: " + e.message); }
  };

  const sw = async (on) => {
    if (!confirm(`${on ? "Sepnout" : "Rozepnout"} kontakt na ${mod.id}?`)) return;
    setMsg("");
    try { await api.contactSwitch(mod.id, on); onChange && onChange(); }
    catch (e) { setMsg("Chyba: " + e.message); }
  };

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <h3 style={{ margin: 0 }}>{mod.id}</h3>
        {cfg && <span className={cfg.contact_on ? "badge-on" : "badge-off"}>{cfg.contact_on ? "kontakt sepnut" : "kontakt rozepnut"}</span>}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))", gap: 12, marginTop: 10 }}>
        <label style={lbl}>Horní mez SOC (%) — sepnout<input type="number" min="0" max="100" value={f.upper_soc} onChange={upd("upper_soc")} /></label>
        <label style={lbl}>Dolní mez SOC (%) — rozepnout<input type="number" min="0" max="100" value={f.lower_soc} onChange={upd("lower_soc")} /></label>
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, fontSize: 14 }}>
        <input type="checkbox" checked={f.enabled} onChange={upd("enabled")} style={{ width: "auto" }} />
        Automatické spínání dle SOC zapnuto
      </label>
      {cfg?.last_decision && <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>{cfg.last_decision}</p>}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
        <button className="btn primary" onClick={save}>Uložit</button>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={() => sw(true)}>Sepnout (test)</button>
        <button className="btn" onClick={() => sw(false)}>Rozepnout (test)</button>
        {msg && <span className="muted">{msg}</span>}
      </div>
    </div>
  );
}

export default function Contact() {
  const [mods, setMods] = useState(null);
  const [cfgs, setCfgs] = useState({});
  const [err, setErr] = useState("");

  const load = () => {
    api.controlModules().then(setMods).catch((e) => setErr(e.message));
    api.contactList()
      .then((list) => setCfgs(Object.fromEntries(list.map((c) => [c.device_id, c]))))
      .catch(() => {});
  };
  useEffect(() => { load(); }, []);

  if (err) return <main><p className="error">{err}</p></main>;
  if (!mods) return <main><p className="muted">Načítám…</p></main>;
  return (
    <main>
      <h2 style={{ marginTop: 0 }}>Spínání kontaktu dle SOC</h2>
      <p className="muted" style={{ fontSize: 13 }}>
        Sepne suchý kontakt (relé) měniče při dosažení horní meze SOC a rozepne při poklesu na dolní mez (hystereze).
        Nejdřív otestuj ruční sepnutí/rozepnutí — měnič musí mít Load Control v režimu, který respektuje softwarové přepnutí.
      </p>
      {!mods.length && <p className="muted">Žádný řiditelný měnič (goodwe).</p>}
      {mods.map((m) => <ContactRow key={m.id} mod={m} cfg={cfgs[m.id]} onChange={load} />)}
    </main>
  );
}
