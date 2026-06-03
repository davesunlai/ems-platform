import { useEffect, useState } from "react";
import { api } from "../api";

const ROLES = ["viewer", "operator", "admin"];

export default function Users() {
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  const [nu, setNu] = useState({ username: "", password: "", role: "viewer" });

  const load = () => api.listUsers().then(setUsers).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const create = async () => {
    setErr("");
    try { await api.createUser(nu); setNu({ username: "", password: "", role: "viewer" }); load(); }
    catch (e) { setErr(e.message); }
  };
  const setRole = async (id, role) => { try { await api.updateUser(id, { role }); load(); } catch (e) { setErr(e.message); } };
  const toggle = async (u) => { try { await api.updateUser(u.id, { active: !u.active }); load(); } catch (e) { setErr(e.message); } };
  const remove = async (id) => { if (!confirm("Smazat uživatele?")) return; try { await api.deleteUser(id); load(); } catch (e) { setErr(e.message); } };

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
            <input type="password" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Role</label>
            <select value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <button className="btn primary" onClick={create}>Vytvořit</button>
        </div>
        <p className="error">{err}</p>
      </div>

      <div className="panel">
        <h3>Uživatelé</h3>
        <table>
          <thead><tr><th>ID</th><th>Uživatel</th><th>Role</th><th>Stav</th><th></th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td className="muted">{u.id}</td>
                <td>{u.username}</td>
                <td>
                  <select className="role" value={u.role} onChange={(e) => setRole(u.id, e.target.value)}
                          style={{ background: "var(--bg)", color: "var(--fg)", border: "1px solid var(--border)", borderRadius: 6, padding: "4px 8px" }}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td><span className={u.active ? "badge-on" : "badge-off"}>{u.active ? "aktivní" : "vypnutý"}</span></td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn" onClick={() => toggle(u)} style={{ marginRight: 8 }}>{u.active ? "Vypnout" : "Zapnout"}</button>
                  <button className="btn danger" onClick={() => remove(u.id)}>Smazat</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
