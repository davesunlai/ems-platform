import { useState } from "react";
import { useAuth } from "../auth";
import { api } from "../api";
import { PRESETS, VAR_LABELS, resolveVars, applyTheme } from "../theme";

const EDIT_VARS = ["--bg", "--panel", "--border", "--fg", "--muted", "--green", "--blue", "--amber"];

export default function Vzhled() {
  const { user } = useAuth();
  const [sel, setSel] = useState(user?.theme || "midnight");
  const [custom, setCustom] = useState(() => ({ ...resolveVars(user?.theme || "midnight", user?.theme_custom) }));
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const note = (t) => { setMsg(t); setErr(""); setTimeout(() => setMsg(""), 2500); };

  const pickPreset = async (id) => {
    setSel(id); applyTheme(id, null);
    setCustom({ ...PRESETS[id].vars });
    try { await api.setTheme(id, null); note(`Motiv „${PRESETS[id].name}“ uložen.`); }
    catch (e) { setErr(e.message); }
  };

  const seedFrom = (id) => { const v = { ...PRESETS[id].vars }; setCustom(v); setSel("custom"); applyTheme("custom", v); };

  const setVar = (k, val) => {
    const next = { ...custom, [k]: val };
    setCustom(next); setSel("custom"); applyTheme("custom", next);
  };

  const saveCustom = async () => {
    setSel("custom"); applyTheme("custom", custom);
    try { await api.setTheme("custom", custom); note("Vlastní motiv uložen."); }
    catch (e) { setErr(e.message); }
  };

  const swatchKeys = ["--bg", "--panel", "--green", "--blue", "--amber"];

  return (
    <main>
      <div className="panel" style={{ marginBottom: 18 }}>
        <h3 style={{ marginTop: 0 }}>Vzhled (motiv)</h3>
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
          Vyber barevný motiv aplikace. Volba se uloží k tvému účtu a projeví se i na dalších zařízeních.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
          {Object.entries(PRESETS).map(([id, p]) => (
            <div key={id} onClick={() => pickPreset(id)}
              style={{ cursor: "pointer", borderRadius: 10, padding: 12,
                border: `2px solid ${sel === id ? "var(--blue)" : "var(--border)"}`,
                background: p.vars["--panel"] }}>
              <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
                {swatchKeys.map((k) => (
                  <span key={k} style={{ width: 20, height: 20, borderRadius: 5, background: p.vars[k], border: "1px solid rgba(128,128,128,.3)" }} />
                ))}
              </div>
              <div style={{ color: p.vars["--fg"], fontSize: 13, fontWeight: 600 }}>{p.name}</div>
              {sel === id && <div style={{ color: p.vars["--muted"], fontSize: 11, marginTop: 2 }}>aktivní</div>}
            </div>
          ))}
        </div>
        {msg && <p className="muted" style={{ marginTop: 12 }}>{msg}</p>}
        {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Vlastní motiv</h3>
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
          Uprav si jednotlivé barvy. Změny se hned projeví jako náhled; tlačítkem uložíš.
          Můžeš vyjít z některého motivu:
        </p>
        <div className="row" style={{ gap: 8, marginBottom: 14 }}>
          {Object.entries(PRESETS).map(([id, p]) => (
            <button key={id} className="btn" onClick={() => seedFrom(id)}>{p.name}</button>
          ))}
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
        <div className="row" style={{ gap: 8, marginTop: 16 }}>
          <button className="btn primary" onClick={saveCustom}>Uložit vlastní motiv</button>
          <button className="btn" onClick={() => pickPreset("midnight")}>Zpět na výchozí</button>
        </div>
      </div>
    </main>
  );
}
