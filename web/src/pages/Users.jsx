import { useEffect, useState } from "react";
import { api } from "../api";
import { UI_CATALOG } from "../uiCatalog";

const BUILTIN_ROLES = ["viewer", "operator", "admin"];
const BASE_CZ = { viewer: "jen čtení", operator: "čtení + řízení", admin: "vše" };
const empty = { username: "", password: "", role: "viewer", email: "", full_name: "", phone: "", note: "" };

export default function Users() {
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  const [nu, setNu] = useState(empty);

  const [roles, setRoles] = useState({ builtin: [], custom: [] });
  const ROLES = [...BUILTIN_ROLES, ...roles.custom.map((r) => r.name)];
  const load = () => {
    api.listUsers().then(setUsers).catch((e) => setErr(e.message));
    api.listRoles().then(setRoles).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    setErr("");
    try {
      await api.createUser({
        username: nu.username, password: nu.password || null, role: nu.role,
        email: nu.email || null, full_name: nu.full_name || null,
        phone: nu.phone || null, note: nu.note || null,
      });
      setNu(empty); load();
    } catch (e) { setErr(e.message); }
  };
  const setRole = async (id, role) => { try { await api.updateUser(id, { role }); load(); } catch (e) { setErr(e.message); } };
  const toggle = async (u) => { try { await api.updateUser(u.id, { active: !u.active }); load(); } catch (e) { setErr(e.message); } };
  const remove = async (id) => { if (!confirm("Smazat uživatele?")) return; try { await api.deleteUser(id); load(); } catch (e) { setErr(e.message); } };
  const editName = async (u) => {
    const full_name = prompt(`Jméno uživatele ${u.username}:`, u.full_name || "");
    if (full_name === null) return;
    try { await api.updateUser(u.id, { full_name: full_name || null }); load(); } catch (e) { setErr(e.message); }
  };
  const editEmail = async (u) => {
    const email = prompt(`E-mail uživatele ${u.username}:`, u.email || "");
    if (email === null) return;
    try { await api.updateUser(u.id, { email: email || null }); load(); } catch (e) { setErr(e.message); }
  };
  const editPhone = async (u) => {
    const phone = prompt(`Telefon uživatele ${u.username}:`, u.phone || "");
    if (phone === null) return;
    try { await api.updateUser(u.id, { phone: phone || "" }); load(); } catch (e) { setErr(e.message); }
  };
  const resetPw = async (u) => {
    if (!confirm(`Poslat uživateli ${u.username} e-mail s odkazem pro nastavení hesla?`)) return;
    try { const r = await api.sendReset(u.id); setErr(""); alert(r.detail || "E-mail odeslán."); }
    catch (e) { setErr(e.message); }
  };

  return (
    <main>
      <div className="panel" style={{ marginBottom: 22 }}>
        <h3>Nový uživatel</h3>
        <div className="row">
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Uživatel</label>
            <input value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Heslo</label>
            <input type="password" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} placeholder="prázdné = pošle se e-mail s odkazem" />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Jméno</label>
            <input value={nu.full_name} onChange={(e) => setNu({ ...nu, full_name: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>E-mail</label>
            <input value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Telefon</label>
            <input value={nu.phone} onChange={(e) => setNu({ ...nu, phone: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Role</label>
            <select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <button className="btn primary" onClick={create} disabled={!nu.username.trim()}>Vytvořit</button>
        </div>
        <p className="error">{err}</p>
      </div>

      <div className="panel">
        <h3>Uživatelé</h3>
        <table>
          <thead><tr><th>ID</th><th>Uživatel</th><th>Jméno</th><th>E-mail</th><th>Telefon</th><th>Role</th><th>Stav</th><th></th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td className="muted">{u.id}</td>
                <td>{u.username}</td>
                <td className="muted">{u.full_name || "—"}
                  <button className="btn" style={{ marginLeft: 6, padding: "2px 7px" }} onClick={() => editName(u)}>✎</button>
                </td>
                <td className="muted" style={{ fontSize: 13 }}>
                  {u.email || "—"}
                  <button className="btn" style={{ marginLeft: 6, padding: "2px 7px" }} onClick={() => editEmail(u)}>✎</button>
                </td>
                <td className="muted" style={{ fontSize: 13 }}>
                  {u.phone || "—"}
                  <button className="btn" style={{ marginLeft: 6, padding: "2px 7px" }} onClick={() => editPhone(u)}>✎</button>
                </td>
                <td>
                  <select className="role" value={u.role} onChange={(e) => setRole(u.id, e.target.value)}
                          style={{ background: "var(--bg)", color: "var(--fg)", border: "1px solid var(--border)", borderRadius: 6, padding: "4px 8px" }}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td><span className={u.active ? "badge-on" : "badge-off"}>{u.active ? "aktivní" : "vypnutý"}</span></td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="btn" onClick={() => resetPw(u)} style={{ marginRight: 8 }}>Reset hesla</button>
                  <button className="btn" onClick={() => toggle(u)} style={{ marginRight: 8 }}>{u.active ? "Vypnout" : "Zapnout"}</button>
                  <button className="btn danger" onClick={() => remove(u.id)}>Smazat</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <RolesEditor roles={roles} onChange={load} />
    </main>
  );
}

// ---------------- Role a viditelnost prvků UI (user1, user2, …) ----------------
function RolesEditor({ roles, onChange }) {
  const [sel, setSel] = useState(null);          // jméno editované role
  const [draft, setDraft] = useState(null);      // {name, base, hidden:Set}
  const [newName, setNewName] = useState("");
  const [msg, setMsg] = useState("");
  const open = (r) => { setSel(r.name); setDraft({ name: r.name, base: r.base, hidden: new Set(r.hidden || []) }); setMsg(""); };
  const create = async () => {
    const n = newName.trim(); if (!n) return;
    try { await api.createRole({ name: n, base: "viewer", hidden: [] }); setNewName(""); onChange(); setMsg(`Role ${n} založena — nastav viditelnost.`); }
    catch (e) { setMsg(e.message); }
  };
  const save = async () => {
    try { await api.saveRole(draft.name, { name: draft.name, base: draft.base, hidden: [...draft.hidden] }); onChange(); setMsg("Uloženo. Uživatelé s touto rolí uvidí změnu po dalším přihlášení / obnovení stránky."); }
    catch (e) { setMsg(e.message); }
  };
  const del = async () => {
    if (!window.confirm(`Smazat roli ${draft.name}?`)) return;
    try { await api.deleteRole(draft.name); setSel(null); setDraft(null); onChange(); } catch (e) { setMsg(e.message); }
  };
  const toggle = (key, on) => { const h = new Set(draft.hidden); on ? h.delete(key) : h.add(key); setDraft({ ...draft, hidden: h }); };
  const togglePage = (g, on) => {
    const h = new Set(draft.hidden);
    [g.page, ...g.items.map((i) => i.key)].forEach((k) => (on ? h.delete(k) : h.add(k)));
    setDraft({ ...draft, hidden: h });
  };
  return (
    <div className="panel" style={{ marginTop: 22 }}>
      <h3>Role a viditelnost</h3>
      <p className="muted" style={{ fontSize: 12.5, marginTop: -4 }}>
        Vestavěné role (viewer/operator/admin) vidí vše dle oprávnění. Vlastní role (user1, user2, …) dědí základní
        oprávnění a navíc mají zaškrtávací mapu: <b>zaškrtnuto = viditelné</b>, odškrtnuto = skryté (celá stránka v menu i jednotlivé panely).
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
        {roles.custom.map((r) => (
          <button key={r.name} className={"btn" + (sel === r.name ? " primary" : "")} onClick={() => open(r)}>
            {r.name} <span className="muted" style={{ fontSize: 11 }}>({BASE_CZ[r.base] || r.base}{r.hidden?.length ? ` · skryto ${r.hidden.length}` : ""})</span>
          </button>))}
        <input placeholder="nová role (např. user1)" value={newName} onChange={(e) => setNewName(e.target.value)} style={{ width: 170 }} />
        <button className="btn" onClick={create} disabled={!newName.trim()}>+ založit</button>
      </div>
      {draft && (
        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
            <b>{draft.name}</b>
            <label style={{ fontSize: 13 }}>základní oprávnění:{" "}
              <select value={draft.base} onChange={(e) => setDraft({ ...draft, base: e.target.value })}>
                {BUILTIN_ROLES.map((b) => <option key={b} value={b}>{b} — {BASE_CZ[b]}</option>)}
              </select>
            </label>
            <button className="btn primary" onClick={save}>Uložit</button>
            <button className="btn" onClick={del} style={{ color: "#f85149" }}>smazat roli</button>
            {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 10 }}>
            {UI_CATALOG.map((g) => {
              const pageOn = !draft.hidden.has(g.page);
              return (
                <div key={g.page} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px", opacity: pageOn ? 1 : 0.6 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 13.5 }}>
                    <input type="checkbox" checked={pageOn} onChange={(e) => togglePage(g, e.target.checked)} />
                    {g.label} <span className="muted" style={{ fontWeight: 400, fontSize: 11 }}>{g.path}</span>
                  </label>
                  {g.items.map((it) => (
                    <label key={it.key} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, marginLeft: 18, marginTop: 3 }}>
                      <input type="checkbox" disabled={!pageOn} checked={pageOn && !draft.hidden.has(it.key)} onChange={(e) => toggle(it.key, e.target.checked)} />
                      {it.label}
                    </label>))}
                </div>);
            })}
          </div>
        </div>
      )}
    </div>
  );
}
