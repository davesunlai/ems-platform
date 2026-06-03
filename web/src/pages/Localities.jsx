import { useEffect, useState } from "react";
import { api } from "../api";

const emptyLoc = { name: "", address: "", region: "CZ", note: "" };

function LocalityCard({ loc, allUsers, allModules, onChange }) {
  const [uSel, setUSel] = useState("");
  const [dSel, setDSel] = useState("");

  const assignedU = new Set(loc.users.map((u) => u.id));
  const assignedD = new Set(loc.devices.map((d) => d.id));
  const freeUsers = allUsers.filter((u) => !assignedU.has(u.id));
  const freeMods = allModules.filter((m) => !assignedD.has(m.id));

  const addU = async () => { if (uSel) { await api.assignUser(loc.id, Number(uSel)); setUSel(""); onChange(); } };
  const rmU = async (uid) => { await api.unassignUser(loc.id, uid); onChange(); };
  const addD = async () => { if (dSel) { await api.assignDevice(loc.id, dSel); setDSel(""); onChange(); } };
  const rmD = async (mid) => { await api.unassignDevice(loc.id, mid); onChange(); };
  const rename = async () => {
    const name = prompt("Název lokality:", loc.name); if (name === null) return;
    const note = prompt("Poznámka:", loc.note || ""); if (note === null) return;
    await api.updateLocality(loc.id, { name, note }); onChange();
  };
  const del = async () => { if (confirm(`Smazat lokalitu „${loc.name}"? Zařízení se odpojí, uživatelské vazby se zruší.`)) { await api.deleteLocality(loc.id); onChange(); } };

  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h3 style={{ margin: 0 }}>{loc.name}</h3>
        <span className="muted" style={{ fontSize: 13 }}>{[loc.address, loc.region].filter(Boolean).join(" · ")}</span>
        <div style={{ marginLeft: "auto" }}>
          <button className="btn" onClick={rename} style={{ marginRight: 8 }}>Upravit</button>
          <button className="btn danger" onClick={del}>Smazat</button>
        </div>
      </div>
      {loc.note && <p className="muted" style={{ fontSize: 13, marginTop: 6 }}>{loc.note}</p>}

      <div className="row" style={{ marginTop: 14, alignItems: "flex-start", gap: 30 }}>
        <div style={{ flex: 1 }}>
          <label className="muted" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}>Zařízení</label>
          <div style={{ margin: "6px 0" }}>
            {loc.devices.length === 0 && <span className="muted">žádné</span>}
            {loc.devices.map((d) => (
              <span key={d.id} className="role" style={{ marginRight: 6, marginBottom: 6, display: "inline-block" }}>
                {d.name || d.id} <button className="linkx" onClick={() => rmD(d.id)}>×</button>
              </span>
            ))}
          </div>
          <div className="row" style={{ gap: 6 }}>
            <select value={dSel} onChange={(e) => setDSel(e.target.value)}>
              <option value="">— přidat zařízení —</option>
              {freeMods.map((m) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)}
            </select>
            <button className="btn" onClick={addD} disabled={!dSel}>Přidat</button>
          </div>
        </div>

        <div style={{ flex: 1 }}>
          <label className="muted" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}>Uživatelé</label>
          <div style={{ margin: "6px 0" }}>
            {loc.users.length === 0 && <span className="muted">žádní</span>}
            {loc.users.map((u) => (
              <span key={u.id} className="role" style={{ marginRight: 6, marginBottom: 6, display: "inline-block" }}>
                {u.full_name || u.username} <button className="linkx" onClick={() => rmU(u.id)}>×</button>
              </span>
            ))}
          </div>
          <div className="row" style={{ gap: 6 }}>
            <select value={uSel} onChange={(e) => setUSel(e.target.value)}>
              <option value="">— přidat uživatele —</option>
              {freeUsers.map((u) => <option key={u.id} value={u.id}>{u.full_name ? `${u.full_name} (${u.username})` : u.username}</option>)}
            </select>
            <button className="btn" onClick={addU} disabled={!uSel}>Přidat</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Localities() {
  const [locs, setLocs] = useState([]);
  const [users, setUsers] = useState([]);
  const [mods, setMods] = useState([]);
  const [nl, setNl] = useState(emptyLoc);
  const [err, setErr] = useState("");

  const load = () => api.listLocalities().then(setLocs).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.listUsers().then(setUsers).catch(() => {});
    api.listModules().then(setMods).catch(() => {});
  }, []);

  const create = async () => {
    setErr("");
    try { await api.createLocality({ ...nl, address: nl.address || null, note: nl.note || null }); setNl(emptyLoc); load(); }
    catch (e) { setErr(e.message); }
  };

  return (
    <main>
      <div className="panel" style={{ marginBottom: 20 }}>
        <h3>Nová lokalita</h3>
        <div className="row">
          <div className="field" style={{ marginBottom: 0 }}><label>Název</label>
            <input value={nl.name} onChange={(e) => setNl({ ...nl, name: e.target.value })} /></div>
          <div className="field" style={{ marginBottom: 0 }}><label>Adresa</label>
            <input value={nl.address} onChange={(e) => setNl({ ...nl, address: e.target.value })} /></div>
          <div className="field" style={{ marginBottom: 0, maxWidth: 90 }}><label>Region</label>
            <input value={nl.region} onChange={(e) => setNl({ ...nl, region: e.target.value })} /></div>
          <div className="field" style={{ marginBottom: 0 }}><label>Poznámka</label>
            <input value={nl.note} onChange={(e) => setNl({ ...nl, note: e.target.value })} /></div>
          <button className="btn primary" onClick={create} disabled={!nl.name.trim()}>Přidat lokalitu</button>
        </div>
        <p className="error">{err}</p>
      </div>

      {locs.length === 0 && <p className="muted">Zatím žádné lokality.</p>}
      {locs.map((l) => (
        <LocalityCard key={l.id} loc={l} allUsers={users} allModules={mods} onChange={load} />
      ))}
    </main>
  );
}
