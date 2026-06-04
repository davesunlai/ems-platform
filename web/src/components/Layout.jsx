import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { api } from "../api";

function AlertsBell() {
  const [data, setData] = useState({ count: 0, alerts: [] });
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const load = () => api.alerts().then(setData).catch(() => {});
    load(); const t = setInterval(load, 180000); return () => clearInterval(t);
  }, []);
  const count = data.count || 0;
  const triColor = count > 0 ? "var(--amber, #e0a000)" : "var(--text-muted, #6b6b76)";
  return (
    <div style={{ position: "relative" }}>
      <button className="btn" onClick={() => setOpen((o) => !o)} title="Výstrahy"
        style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ color: triColor, fontSize: 16, lineHeight: 1 }}>⚠</span>
        {count > 0 && (
          <span style={{ background: "var(--amber, #e0a000)", color: "#1a1a1f", borderRadius: 9,
            fontSize: 11, fontWeight: 700, minWidth: 17, height: 17, padding: "0 4px",
            display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{count}</span>
        )}
      </button>
      {open && (
        <div style={{ position: "absolute", right: 0, top: "calc(100% + 8px)", width: 340, zIndex: 50,
          background: "var(--panel, #1c1c24)", border: "1px solid var(--border, #2a2a35)",
          borderRadius: 10, boxShadow: "0 8px 28px rgba(0,0,0,.45)", maxHeight: 420, overflowY: "auto" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #2a2a35)",
            fontWeight: 600, fontSize: 13 }}>Výstrahy {count > 0 && `(${count})`}</div>
          {count === 0 && <div className="muted" style={{ padding: "14px", fontSize: 13 }}>Žádné aktivní výstrahy.</div>}
          {(data.alerts || []).map((a) => (
            <div key={a.id} style={{ padding: "10px 14px", borderBottom: "1px solid var(--border, #23232b)", fontSize: 13 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                <span style={{ color: "var(--amber, #e0a000)" }}>⚠</span>
                <strong>{a.title}</strong>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{a.locality_name}</div>
              <div style={{ fontSize: 12, marginTop: 2 }}>{a.detail}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SpotChip() {
  const [p, setP] = useState(null);
  useEffect(() => {
    const load = () => api.spot().then((s) => setP(s)).catch(() => {});
    load(); const t = setInterval(load, 30000); return () => clearInterval(t);
  }, []);
  if (!p || p.price == null) return null;
  return <span className="role" title="Spotová cena (OTE)" style={{ color: "var(--blue)", borderColor: "var(--border)" }}>
    spot {Math.round(p.price)} Kč/MWh{p.manual ? " (test)" : ""}
  </span>;
}

export default function Layout() {
  const { user, logout, has } = useAuth();
  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="dot" />
          <b>TERA EMS</b>
          <span>pilot</span>
        </div>
        <nav className="nav">
          <NavLink to="/" end>Dashboard</NavLink>
          {has("control") && <NavLink to="/control">Řízení</NavLink>}
          {has("control") && <NavLink to="/contact">Kontakt</NavLink>}
          {has("admin") && <NavLink to="/automation">Automatizace</NavLink>}
          {has("admin") && <NavLink to="/ewelink">eWeLink</NavLink>}
          {has("admin") && <NavLink to="/billing">Zúčtování</NavLink>}
          {has("admin") && <NavLink to="/localities">Lokality</NavLink>}
          {has("admin") && <NavLink to="/modules">Moduly</NavLink>}
          {has("admin") && <NavLink to="/users">Uživatelé</NavLink>}
        </nav>
        <div className="spacer" />
        <div className="userbox">
          <AlertsBell />
          <SpotChip />
          <span>{user?.username}</span>
          <span className="role">{user?.role}</span>
          <NavLink to="/change-password" className="btn">Změnit heslo</NavLink>
          <button className="btn" onClick={logout}>Odhlásit</button>
        </div>
      </header>
      <Outlet />
    </>
  );
}
