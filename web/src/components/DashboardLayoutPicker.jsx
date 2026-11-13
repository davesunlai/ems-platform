// Vzhled → Rozhraní dashboardu: Schéma toků (TERA) | Panel měniče (LCD) | podle role. Ukládá se do ui_prefs.dashboard_layout.
import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

const OPTS = [
  { v: "flow", l: "Schéma toků", d: "Živé schéma FVE → dům → baterie → síť, auta, TČ, grafy a články baterie.", icon: "🔀" },
  { v: "lcd", l: "Panel měniče (LCD)", d: "Vzhled displeje měniče: záložky PV · BATT · GRID · LOAD · MORE, stavové schéma, tabulky hodnot po fázích.", icon: "📟" },
];

export default function DashboardLayoutPicker() {
  const { user, refreshUser } = useAuth();
  const [msg, setMsg] = useState("");
  const cur = user?.dashboard_layout || "flow";
  const roleDef = user?.dashboard_layout_role || "flow";
  const pick = async (v) => {
    setMsg("");
    try { await api.setPrefs({ dashboard_layout: v }); await refreshUser(); setMsg(v ? "Uloženo — dashboard se přepne." : "Zrušeno — platí výchozí rozhraní role."); }
    catch (e) { setMsg(e.message); }
  };
  return (
    <div className="panel" style={{ marginBottom: 18 }}>
      <h3 style={{ marginTop: 0 }}>📟 Rozhraní dashboardu</h3>
      <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
        Jak vypadá hlavní stránka. Výchozí podle role <b>{user?.role}</b>: {OPTS.find((o) => o.v === roleDef)?.l || roleDef}. Vlastní volba má přednost; ostatní stránky zůstávají stejné.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
        {OPTS.map((o) => (
          <button key={o.v} type="button" className="btn" onClick={() => pick(o.v)}
                  style={{ textAlign: "left", padding: 12, borderColor: cur === o.v ? "var(--blue)" : undefined, outline: cur === o.v ? "1.5px solid var(--blue)" : "none" }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{o.icon} {o.l}{cur === o.v ? <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}> · aktivní</span> : null}</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{o.d}</div>
          </button>))}
      </div>
      <div style={{ marginTop: 8, display: "flex", gap: 10, alignItems: "center" }}>
        <button type="button" className="btn" style={{ fontSize: 12 }} onClick={() => pick(null)}>podle role ({OPTS.find((o) => o.v === roleDef)?.l})</button>
        {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
      </div>
    </div>
  );
}
