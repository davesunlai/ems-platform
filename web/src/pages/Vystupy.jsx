import { useEffect, useState } from "react";
import { api } from "../api";

const empty = {
  name: "", enabled: true, output_kind: "ewelink", target: "", locality_id: "",
  trigger: "surplus",
  upper_soc: 100, lower_soc: 95,
  surplus_kw: 1.5, soc_min: 80, spot_max: "", min_on_min: 10,
};

export default function Vystupy() {
  const [list, setList] = useState([]);
  const [gw, setGw] = useState([]);
  const [ew, setEw] = useState([]);
  const [locs, setLocs] = useState([]);
  const [f, setF] = useState(empty);
  const [editing, setEditing] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(0);

  const load = () => api.listOutputs().then(setList).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.controlModules().then(setGw).catch(() => {});
    api.ewelinkDevices().then((r) => setEw(r.devices || [])).catch(() => {});
    api.listLocalities().then(setLocs).catch(() => {});
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  const targets = f.output_kind === "ewelink"
    ? ew.map((d) => ({ id: d.deviceid, label: d.name || d.deviceid }))
    : gw.map((m) => ({ id: m.id, label: m.name || m.id }));

  const buildParams = () => f.trigger === "soc"
    ? { upper_soc: Number(f.upper_soc), lower_soc: Number(f.lower_soc) }
    : {
        surplus_kw: Number(f.surplus_kw), soc_min: Number(f.soc_min),
        min_on_min: Number(f.min_on_min),
        ...(f.spot_max !== "" && f.spot_max != null ? { spot_max: Number(f.spot_max) } : {}),
      };

  const body = () => ({
    name: f.name.trim(), enabled: f.enabled, output_kind: f.output_kind, target: f.target,
    locality_id: f.locality_id ? Number(f.locality_id) : null, trigger: f.trigger, params: buildParams(),
  });

  const reset = () => { setEditing(null); setF(empty); };

  const save = async () => {
    setErr("");
    try {
      if (editing) await api.updateOutput(editing, body());
      else await api.createOutput(body());
      reset(); load();
    } catch (e) { setErr(e.message); }
  };

  const edit = (o) => {
    setEditing(o.id);
    setF({
      name: o.name, enabled: o.enabled, output_kind: o.output_kind, target: o.target,
      locality_id: o.locality_id || "", trigger: o.trigger,
      upper_soc: o.params.upper_soc ?? 100, lower_soc: o.params.lower_soc ?? 95,
      surplus_kw: o.params.surplus_kw ?? 1.5, soc_min: o.params.soc_min ?? 80,
      spot_max: o.params.spot_max ?? "", min_on_min: o.params.min_on_min ?? 10,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const toggle = async (o) => { try { await api.updateOutput(o.id, { enabled: !o.enabled }); load(); } catch (e) { setErr(e.message); } };
  const remove = async (o) => { if (!confirm(`Smazat výstup „${o.name}“?`)) return; try { await api.deleteOutput(o.id); if (editing === o.id) reset(); load(); } catch (e) { setErr(e.message); } };
  const test = async (o, on) => { setBusy(o.id); setErr(""); try { await api.testOutput(o.id, on); setTimeout(load, 600); } catch (e) { setErr(e.message); } finally { setBusy(0); } };

  const kindLabel = (k) => (k === "ewelink" ? "eWeLink" : "kontakt střídače");
  const trigLabel = (t) => (t === "soc" ? "SoC hystereze" : "přebytek/spot");

  return (
    <main>
      <div className="panel" style={{ marginBottom: 18 }}>
        <h3 style={{ marginTop: 0 }}>{editing ? "Upravit výstup" : "Nový spínací výstup"}</h3>
        <div className="row" style={{ flexWrap: "wrap", alignItems: "flex-end", gap: 12 }}>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Název</label>
            <input value={f.name} placeholder="Ohřev vody" onChange={(e) => setF({ ...f, name: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Cíl</label>
            <select value={f.output_kind} onChange={(e) => setF({ ...f, output_kind: e.target.value, target: "" })}>
              <option value="ewelink">eWeLink spínač</option>
              <option value="goodwe_contact">Kontakt střídače</option>
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Zařízení</label>
            <select value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })}>
              <option value="">— vyber —</option>
              {targets.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Lokalita {f.trigger === "surplus" ? "(nutná)" : "(pro SoC volitelná)"}</label>
            <select value={f.locality_id} onChange={(e) => setF({ ...f, locality_id: e.target.value })}>
              <option value="">— žádná —</option>
              {locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Spouštěč</label>
            <select value={f.trigger} onChange={(e) => setF({ ...f, trigger: e.target.value })}>
              <option value="surplus">Přebytek FVE / levný spot</option>
              <option value="soc">SoC hystereze</option>
            </select>
          </div>
        </div>

        <div className="row" style={{ flexWrap: "wrap", gap: 12, marginTop: 12 }}>
          {f.trigger === "soc" ? (
            <>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>Sepnout při SoC ≥ (%)</label>
                <input value={f.upper_soc} onChange={(e) => setF({ ...f, upper_soc: e.target.value })} style={{ width: 120 }} />
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>Rozepnout při SoC ≤ (%)</label>
                <input value={f.lower_soc} onChange={(e) => setF({ ...f, lower_soc: e.target.value })} style={{ width: 120 }} />
              </div>
            </>
          ) : (
            <>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>Přebytek do sítě ≥ (kW)</label>
                <input value={f.surplus_kw} onChange={(e) => setF({ ...f, surplus_kw: e.target.value })} style={{ width: 130 }} />
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>A SoC ≥ (%)</label>
                <input value={f.soc_min} onChange={(e) => setF({ ...f, soc_min: e.target.value })} style={{ width: 100 }} />
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>Spot ≤ sepni i bez přebytku (Kč/MWh)</label>
                <input value={f.spot_max} placeholder="např. 0" onChange={(e) => setF({ ...f, spot_max: e.target.value })} style={{ width: 160 }} />
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label>Min. doba sepnutí (min)</label>
                <input value={f.min_on_min} onChange={(e) => setF({ ...f, min_on_min: e.target.value })} style={{ width: 120 }} />
              </div>
            </>
          )}
          <button className="btn primary" onClick={save} disabled={!f.name.trim() || !f.target || (f.trigger === "surplus" && !f.locality_id)}>
            {editing ? "Uložit změny" : "Přidat"}
          </button>
          {editing && <button className="btn" onClick={reset}>Zrušit</button>}
        </div>
        {err && <p className="error" style={{ marginTop: 10 }}>{err}</p>}
        <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          {f.trigger === "surplus"
            ? "Sepne, když přebytek FVE do sítě překročí práh a baterie je nabitá aspoň na daný SoC; volitelně sepne i při levném/záporném spotu pod limitem (např. spirálu přes eWeLink). Hystereze a minimální doba sepnutí brání cvakání."
            : "Sepne při dosažení horní meze SoC, rozepne při dolní. Cílem může být kontakt střídače i eWeLink spínač."}
        </p>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Spínací výstupy</h3>
        <table>
          <thead><tr><th>Název</th><th>Cíl</th><th>Spouštěč</th><th>Stav</th><th>Aktivní</th><th>Poslední rozhodnutí</th><th>Test</th><th></th></tr></thead>
          <tbody>
            {list.map((o) => (
              <tr key={o.id}>
                <td>{o.name}</td>
                <td><span className="role">{kindLabel(o.output_kind)}</span><div className="muted" style={{ fontSize: 11, fontFamily: "var(--mono)" }}>{o.target}</div></td>
                <td className="muted">{trigLabel(o.trigger)}</td>
                <td><span className={o.is_on ? "badge-on" : "badge-off"}>{o.is_on ? "sepnuto" : "rozepnuto"}</span></td>
                <td><span className={o.enabled ? "badge-on" : "badge-off"}>{o.enabled ? "ano" : "ne"}</span></td>
                <td className="muted" style={{ fontSize: 12 }}>{o.last_decision || "—"}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="btn" disabled={busy === o.id} onClick={() => test(o, true)} style={{ padding: "2px 8px", marginRight: 4 }}>zap</button>
                  <button className="btn" disabled={busy === o.id} onClick={() => test(o, false)} style={{ padding: "2px 8px" }}>vyp</button>
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="btn" onClick={() => edit(o)} style={{ marginRight: 6 }}>Upravit</button>
                  <button className="btn" onClick={() => toggle(o)} style={{ marginRight: 6 }}>{o.enabled ? "Vypnout" : "Zapnout"}</button>
                  <button className="btn danger" onClick={() => remove(o)}>Smazat</button>
                </td>
              </tr>
            ))}
            {!list.length && <tr><td colSpan="8" className="muted">Zatím žádný výstup.</td></tr>}
          </tbody>
        </table>
      </div>
    </main>
  );
}
