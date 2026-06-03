import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { api } from "../api";

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
          {has("admin") && <NavLink to="/automation">Automatizace</NavLink>}
          {has("admin") && <NavLink to="/localities">Lokality</NavLink>}
          {has("admin") && <NavLink to="/modules">Moduly</NavLink>}
          {has("admin") && <NavLink to="/users">Uživatelé</NavLink>}
        </nav>
        <div className="spacer" />
        <div className="userbox">
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
