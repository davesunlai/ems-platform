import { useEffect, useState, useRef } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { api } from "../api";
import Tour, { tourSeen } from "./Tour";
import { hasLocalTheme, applyGlobalTheme } from "../theme";

function AlertsBell() {
  const [data, setData] = useState({ count: 0, alerts: [], browser_localities: [] });
  const [open, setOpen] = useState(false);
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "unsupported");
  const seen = useRef(null);

  useEffect(() => {
    const load = () => api.alerts().then((d) => {
      setData(d);
      // Browser notifikace: vypal nové výstrahy z lokalit, kde má uživatel zapnutý kanál „prohlížeč".
      const ids = new Set((d.alerts || []).map((a) => a.id));
      if (seen.current === null) { seen.current = ids; return; }   // první načtení neoznamuj
      const brLocs = new Set(d.browser_localities || []);
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        for (const a of d.alerts || []) {
          if (!seen.current.has(a.id) && brLocs.has(a.locality_id)) {
            try { new Notification(`TERA EMS · ${a.title}`, { body: `${a.locality_name || ""}\n${a.detail || ""}` }); } catch { /* ignore */ }
          }
        }
      }
      seen.current = ids;
    }).catch(() => {});
    load(); const t = setInterval(load, 30000); return () => clearInterval(t);
  }, []);

  const enableBrowser = async () => {
    if (typeof Notification === "undefined") return;
    setPerm(await Notification.requestPermission());
  };

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
          borderRadius: 10, boxShadow: "0 8px 28px rgba(0,0,0,.45)", maxHeight: 460, overflowY: "auto" }}>
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
          <div style={{ padding: "10px 14px", borderTop: "1px solid var(--border, #2a2a35)", background: "var(--panel-2, #16161c)" }}>
            {perm !== "granted" && perm !== "unsupported" && (
              <button className="btn" style={{ padding: "4px 10px", fontSize: 12 }} onClick={enableBrowser}>
                Povolit upozornění v prohlížeči
              </button>
            )}
            {perm === "granted" && <div className="muted" style={{ fontSize: 11.5 }}>🖥️ Upozornění v prohlížeči povolena.</div>}
            {perm === "denied" && <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>Prohlížeč má upozornění zakázaná — povol je v nastavení webu.</div>}
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              Kam upozornění chodí (e-mail / prohlížeč) se nastavuje u <b>každé lokality a uživatele</b> (Lokality → uživatel).
            </div>
            <button className="btn" style={{ marginTop: 10, padding: "4px 10px", fontSize: 12 }}
              onClick={async () => { try { await api.testNotification(); setTimeout(() => api.alerts().then(setData).catch(() => {}), 800); } catch { /* ignore */ } }}>
              🔔 Poslat testovací notifikaci
            </button>
          </div>
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
  return <span className="role hide-sm" title="Spotová cena (OTE)" style={{ color: "var(--blue)", borderColor: "var(--border)" }}>
    spot {Math.round(p.price)} Kč/MWh{p.manual ? " (test)" : ""}
  </span>;
}

export default function Layout() {
  const { user, logout, has } = useAuth();
  const [tour, setTour] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => { if (!tourSeen()) setTour(true); }, []);
  // Uživatel bez vlastního vzhledu zdědí globální (nastavený adminem).
  useEffect(() => {
    if (!hasLocalTheme()) api.getGlobalTheme().then(applyGlobalTheme).catch(() => {});
  }, []);
  const close = () => setMenuOpen(false);
  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="dot" />
          <b>TERA EMS</b>
          <span className="hide-sm">pilot</span>
        </div>
        <nav className={`nav ${menuOpen ? "open" : ""}`} onClick={close}>
          <NavLink to="/" end>Dashboard</NavLink>
          {has("control") && <NavLink to="/control">Řízení</NavLink>}
          {has("admin") && <NavLink to="/automation">SPOT</NavLink>}
          {has("admin") && <NavLink to="/ewelink">eWeLink</NavLink>}
          {has("admin") && <NavLink to="/localities">Lokality</NavLink>}
          {has("admin") && <NavLink to="/modules">Moduly</NavLink>}
          {has("admin") && <NavLink to="/users">Uživatelé</NavLink>}
          <div className="nav-account mobile-only">
            <div className="nav-id">{user?.username} · {user?.role}</div>
            <button className="navbtn" onClick={() => setTour(true)}>Průvodce</button>
            <NavLink to="/vzhled">Vzhled</NavLink>
            <NavLink to="/change-password">Změnit heslo</NavLink>
            <button className="navbtn" onClick={logout}>Odhlásit</button>
          </div>
        </nav>
        <div className="spacer" />
        <div className="userbox">
          <AlertsBell />
          <SpotChip />
          <span className="hide-sm">{user?.username}</span>
          <span className="role hide-sm">{user?.role}</span>
          <button className="btn desktop-only" onClick={() => setTour(true)} title="Průvodce systémem">Průvodce</button>
          <NavLink to="/vzhled" className="btn desktop-only">Vzhled</NavLink>
          <NavLink to="/change-password" className="btn desktop-only">Změnit heslo</NavLink>
          <button className="btn desktop-only" onClick={logout}>Odhlásit</button>
          <button className="menu-toggle" aria-label="Menu" onClick={() => setMenuOpen((o) => !o)}>
            {menuOpen ? "✕" : "☰"}
          </button>
        </div>
      </header>
      <Outlet />
      <Tour open={tour} onClose={() => setTour(false)} />
    </>
  );
}
