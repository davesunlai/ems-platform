import { useEffect, useState } from "react";
import { api } from "../api";

const lbl = { display: "flex", flexDirection: "column", gap: 4, fontSize: 13 };

function LocRow({ loc, onSaved }) {
  const [f, setF] = useState({
    billing_start: loc.billing_start || "",
    billing_months: loc.billing_months || 12,
    export_mwh: loc.export_limit_kwh != null ? loc.export_limit_kwh / 1000 : "",
    alert_enabled: !!loc.alert_enabled,
    alert_email: loc.alert_email || "",
    baseline_export: loc.baseline_export_kwh != null ? loc.baseline_export_kwh : "",
    baseline_import: loc.baseline_import_kwh != null ? loc.baseline_import_kwh : "",
  });
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);

  const upd = (k) => (e) =>
    setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const save = async () => {
    setSaving(true); setMsg("");
    try {
      await api.setBilling(loc.id, {
        billing_start: f.billing_start || null,
        billing_months: Number(f.billing_months) || 12,
        export_limit_kwh: f.export_mwh === "" ? null : Math.round(Number(f.export_mwh) * 1000),
        alert_enabled: f.alert_enabled,
        alert_email: f.alert_email || null,
        baseline_export_kwh: f.baseline_export === "" ? null : Number(f.baseline_export),
        baseline_import_kwh: f.baseline_import === "" ? null : Number(f.baseline_import),
      });
      setMsg("Uloženo ✓"); onSaved && onSaved();
    } catch (e) { setMsg("Chyba: " + e.message); }
    finally { setSaving(false); }
  };

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h3 style={{ marginTop: 0 }}>{loc.name}</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))", gap: 12 }}>
        <label style={lbl}>Začátek období<input type="date" value={f.billing_start} onChange={upd("billing_start")} /></label>
        <label style={lbl}>Délka (měsíce)<input type="number" min="1" value={f.billing_months} onChange={upd("billing_months")} /></label>
        <label style={lbl}>Limit přetoků (MWh)<input type="number" step="0.1" value={f.export_mwh} onChange={upd("export_mwh")} placeholder="např. 3.5" /></label>
        <label style={lbl}>E-mail pro upozornění<input type="email" value={f.alert_email} onChange={upd("alert_email")} placeholder="control@…" /></label>
        <label style={lbl}>Dodávka před měřením (kWh)<input type="number" step="0.1" value={f.baseline_export} onChange={upd("baseline_export")} placeholder="od začátku období" /></label>
        <label style={lbl}>Odběr před měřením (kWh)<input type="number" step="0.1" value={f.baseline_import} onChange={upd("baseline_import")} placeholder="od začátku období" /></label>
      </div>
      <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
        Dodávka/odběr před měřením = hodnoty z ČEZ od začátku zúčtovacího období do dne spuštění měření; přičtou se k součtu za období (platí jen pro aktuální období).
      </p>
      <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, fontSize: 13 }}>
        <input type="checkbox" checked={f.alert_enabled} onChange={upd("alert_enabled")} style={{ width: "auto" }} />
        Upozornit e-mailem při překročení limitu přetoků
      </label>
      <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
        Automatické omezení přetoků na 0 přibude v další verzi (nejdřív ověříme chování měniče).
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10 }}>
        <button className="btn" onClick={save} disabled={saving}>{saving ? "Ukládám…" : "Uložit"}</button>
        {msg && <span className="muted">{msg}</span>}
      </div>
    </div>
  );
}

export default function Billing() {
  const [locs, setLocs] = useState(null);
  const [err, setErr] = useState("");
  const load = () => api.listLocalities().then(setLocs).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  if (err) return <main><p className="error">{err}</p></main>;
  if (!locs) return <main><p className="muted">Načítám…</p></main>;
  return (
    <main>
      <h2 style={{ marginTop: 0 }}>Zúčtovací období</h2>
      <p className="muted" style={{ fontSize: 13 }}>
        Nastav začátek a délku zúčtovacího období (dle ČEZ) a limit přetoků. Souhrn po měsících
        a stav přetoků proti limitu uvidíš na dashboardu u dané lokality. Po konci období se počítá znovu od nuly.
      </p>
      {!locs.length && <p className="muted">Nejdřív vytvoř lokalitu na stránce Lokality.</p>}
      {locs.map((l) => <LocRow key={l.id} loc={l} onSaved={load} />)}
    </main>
  );
}
