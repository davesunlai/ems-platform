import { useState } from "react";
import { useAuth } from "../auth";
import { api } from "../api";
import { PRESETS, VAR_LABELS, resolveVars, applyTheme } from "../theme";

const EDIT_VARS = ["--bg", "--panel", "--border", "--fg", "--muted", "--green", "--blue", "--amber"];
const SW = ["--bg", "--panel", "--green", "--blue", "--amber"];

export default function Vzhled() {
  const { user } = useAuth();
  const [sel, setSel] = useState(user?.theme || "midnight");
  const [saved, setSaved] = useState(() => (user?.theme_saved || []));
  const [custom, setCustom] = useState(() => ({ ...resolveVars(user?.theme || "midnight", user?.theme_custom, user?.theme_saved) }));
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const note = (t) => { setMsg(t); setErr(""); setTimeout(() => setMsg(""), 2500); };

  // persist active theme + custom + saved list
  const persist = async (theme, customVars, savedList) => {
    applyTheme(theme, customVars, savedList);
    try { await api.setTheme(theme, customVars || null, savedList); }
    catch (e) { setErr(e.message); }
  };

  const pickPreset = async (id) => {
    setSel(id); setCustom({ ...PRESETS[id].vars });
    await persist(id, null, saved); note(`Motiv „${PRESETS[id].name}“ nastaven.`);
  };

  const pickSaved = async (it) => {
    setSel("saved:" + it.name); setCustom({ ...it.vars });
    await persist("saved:" + it.name, it.vars, saved); note(`Motiv „${it.name}“ nastaven.`);
  };

  const delSaved = async (nm) => {
    if (!confirm(`Smazat uložený motiv „${nm}“?`)) return;
    const list = saved.filter((s) => s.name !== nm);
    setSaved(list);
    const active = sel === "saved:" + nm ? "midnight" : sel;
    if (active === "midnight") setSel("midnight");
    await persist(active, active === "custom" ? custom : null, list);
    note(`Motiv „${nm}“ smazán.`);
  };

  const seedFrom = (id) => { const v = { ...PRESETS[id].vars }; setCustom(v); setSel("custom"); applyTheme("custom", v, saved); };
  const setVar = (k, val) => { const next = { ...custom, [k]: val }; setCustom(next); setSel("custom"); applyTheme("custom", next, saved); };

  const saveAs = async () => {
    const nm = name.trim();
    if (!nm) { setErr("Zadej název motivu."); return; }
    const list = [...saved.filter((s) => s.name !== nm), { name: nm, vars: { ...custom } }];
    setSaved(list); setSel("saved:" + nm); setName("");
    await persist("saved:" + nm, custom, list); note(`Uloženo jako „${nm}“.`);
  };

  return (
    <main>
      <div className="panel" style={{ marginBottom: 18 }}>
        <h3 style={{ marginTop: 0 }}>Vzhled (motiv)</h3>
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
          Volba se uloží k tvému účtu a projeví se i na dalších zařízeních.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
          {Object.entries(PRESETS).map(([id, p]) => (
            <div key={id} onClick={() => pickPreset(id)}
              style={{ cursor: "pointer", borderRadius: 10, padding: 12,
                border: `2px solid ${sel === id ? "var(--blue)" : "var(--border)"}`, background: p.vars["--panel"] }}>
              <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
                {SW.map((k) => <span key={k} style={{ width: 20, height: 20, borderRadius: 5, background: p.vars[k], border: "1px solid rgba(128,128,128,.3)" }} />)}
              </div>
              <div style={{ color: p.vars["--fg"], fontSize: 13, fontWeight: 600 }}>{p.name}</div>
              {sel === id && <div style={{ color: p.vars["--muted"], fontSize: 11, marginTop: 2 }}>aktivní</div>}
            </div>
          ))}
        </div>
        {msg && <p className="muted" style={{ marginTop: 12 }}>{msg}</p>}
        {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}
      </div>

      {saved.length > 0 && (
        <div className="panel" style={{ marginBottom: 18 }}>
          <h3 style={{ marginTop: 0 }}>Moje uložené motivy</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
            {saved.map((it) => {
              const active = sel === "saved:" + it.name;
              return (
                <div key={it.name}
                  style={{ borderRadius: 10, padding: 12, position: "relative",
                    border: `2px solid ${active ? "var(--blue)" : "var(--border)"}`, background: it.vars["--panel"] }}>
                  <div onClick={() => pickSaved(it)} style={{ cursor: "pointer" }}>
                    <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
                      {SW.map((k) => <span key={k} style={{ width: 20, height: 20, borderRadius: 5, background: it.vars[k] || "#888", border: "1px solid rgba(128,128,128,.3)" }} />)}
                    </div>
                    <div style={{ color: it.vars["--fg"], fontSize: 13, fontWeight: 600 }}>{it.name}</div>
                    {active && <div style={{ color: it.vars["--muted"], fontSize: 11, marginTop: 2 }}>aktivní</div>}
                  </div>
                  <button className="btn" onClick={() => delSaved(it.name)} title="Smazat"
                    style={{ position: "absolute", top: 6, right: 6, padding: "1px 7px", fontSize: 12 }}>×</button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Vlastní motiv</h3>
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
          Uprav si barvy (živý náhled), pojmenuj a ulož — pak se k němu vrátíš v „Moje uložené motivy“, i když mezitím zkoušíš jiné.
          Můžeš vyjít z některého motivu:
        </p>
        <div className="row" style={{ gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
          {Object.entries(PRESETS).map(([id, p]) => <button key={id} className="btn" onClick={() => seedFrom(id)}>{p.name}</button>)}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
          {EDIT_VARS.map((k) => (
            <label key={k} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
              <input type="color" value={custom[k] || "#000000"} onChange={(e) => setVar(k, e.target.value)}
                style={{ width: 42, height: 30, border: "1px solid var(--border)", borderRadius: 6, background: "none", padding: 0, cursor: "pointer" }} />
              <span>{VAR_LABELS[k] || k}</span>
              <span className="muted" style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 12 }}>{custom[k]}</span>
            </label>
          ))}
        </div>
        <div className="row" style={{ gap: 8, marginTop: 16, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Název motivu</label>
            <input value={name} placeholder="např. Můj noční" onChange={(e) => setName(e.target.value)} style={{ width: 200 }} />
          </div>
          <button className="btn primary" onClick={saveAs} disabled={!name.trim()}>Uložit jako…</button>
          <button className="btn" onClick={() => pickPreset("midnight")}>Zpět na výchozí</button>
        </div>
      </div>
    </main>
  );
}
