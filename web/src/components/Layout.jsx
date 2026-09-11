import { useEffect, useState, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { PAGE_BY_PATH } from "../uiCatalog";
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

// Struktura menu (sekce → položky). perm = potřebné oprávnění, vk = klíč viditelnosti role.
const NAV_GROUPS = [
  { label: "Přehled", icon: "📊", items: [
    { to: "/", end: true, label: "Dashboard", vk: "page:dashboard" },
    { to: "/heatpump", label: "🌀 Tepelné čerpadlo", vk: "page:heatpump" },
  ]},
  { label: "Řízení", icon: "🎛", items: [
    { to: "/control", label: "Řízení (plánovač, časový plán, spotřebiče)", perm: "control", vk: "page:control" },
    { to: "/automation", label: "SPOT pravidla", perm: "admin", vk: "page:automation" },
    { to: "/ewelink", label: "eWeLink spínače", perm: "admin", vk: "page:ewelink" },
  ]},
  { label: "Zařízení", icon: "🔌", items: [
    { to: "/emsboxes", label: "📦 EMSBOXy (fleet)", vk: "page:emsboxes" },
    { to: "/modules", label: "Moduly", perm: "admin", vk: "page:modules" },
    { to: "/localities", label: "Lokality", perm: "admin", vk: "page:localities" },
  ]},
  { label: "Správa", icon: "⚙️", items: [
    { to: "/users", label: "Uživatelé a role", perm: "admin", vk: "page:users" },
  ]},
];

function useVersion() {
  const [v, setV] = useState("");
  useEffect(() => {
    fetch("/api/version").then((r) => r.json()).then((d) => setV(d.version ? `v${d.version}` : "")).catch(() => {});
  }, []);
  return v;
}

export default function Layout() {
  const ver = useVersion();
  const { user, logout, has, vis } = useAuth();
  const location = useLocation();
  const [tour, setTour] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [grpOpen, setGrpOpen] = useState(null);
  useEffect(() => { setGrpOpen(null); setMenuOpen(false); }, [location.pathname]);
  useEffect(() => { if (!tourSeen()) setTour(true); }, []);
  // Uživatel bez vlastního vzhledu zdědí globální (nastavený adminem).
  useEffect(() => {
    if (!hasLocalTheme()) api.getGlobalTheme().then(applyGlobalTheme).catch(() => {});
  }, []);
  const close = () => { setMenuOpen(false); setGrpOpen(null); };
  return (
    <>
      <header className="topbar">
        <NavLink to="/" className="brand" title="Přejít na dashboard"
                 style={{ textDecoration: "none", color: "inherit", cursor: "pointer" }}>
          <span className="dot" />
          <b>TERA EMS</b>
          <span className="hide-sm" title="verze platformy">{ver}</span>
        </NavLink>
        <nav className={`nav ${menuOpen ? "open" : ""}`}>
          {/* desktop: sekce s rozbalením · mobil/úzké okno: plochý seznam s nadpisy sekcí */}
          {NAV_GROUPS.map((g) => {
            const items = g.items.filter((it) => (!it.perm || has(it.perm)) && (!it.vk || vis(it.vk)));
            if (!items.length) return null;
            const activeIn = items.some((it) => (it.end ? location.pathname === it.to : location.pathname.startsWith(it.to)));
            return (
              <div key={g.label} className={`navgrp ${grpOpen === g.label ? "open" : ""} ${activeIn ? "active" : ""}`}
                   onMouseEnter={() => setGrpOpen(g.label)} onMouseLeave={() => setGrpOpen(null)}>
                <button className="navgrp-btn desktop-only" onClick={() => setGrpOpen(grpOpen === g.label ? null : g.label)}>
                  {g.icon} {g.label} <span className="navgrp-caret">▾</span>
                </button>
                <div className="navgrp-hdr mobile-only">{g.icon} {g.label}</div>
                <div className="navgrp-items">
                  {items.map((it) => <NavLink key={it.to} to={it.to} end={it.end} onClick={close}>{it.label}</NavLink>)}
                </div>
              </div>);
          })}
          <div className="nav-account mobile-only">
            <div className="nav-id">{user?.username} · {user?.role}</div>
            <button className="navbtn" onClick={() => { close(); setTour(true); }}>Průvodce</button>
            {vis("page:vzhled") && <NavLink to="/vzhled" onClick={close}>Vzhled</NavLink>}
            <NavLink to="/change-password" onClick={close}>Změnit heslo</NavLink>
            <button className="navbtn" onClick={logout}>Odhlásit</button>
          </div>
        </nav>
        <div className="spacer" />
        <div className="userbox">
          <AlertsBell />
          <SpotChip />
          <div className={`navgrp ${grpOpen === "účet" ? "open" : ""} desktop-only`}
               onMouseEnter={() => setGrpOpen("účet")} onMouseLeave={() => setGrpOpen(null)}>
            <button className="navgrp-btn" onClick={() => setGrpOpen(grpOpen === "účet" ? null : "účet")}>
              👤 {user?.username} <span className="navgrp-caret">▾</span>
            </button>
            <div className="navgrp-items right">
              <div className="nav-id">{user?.username} · {user?.role}</div>
              <button className="navbtn" onClick={() => { setGrpOpen(null); setTour(true); }}>Průvodce</button>
              {vis("page:vzhled") && <NavLink to="/vzhled" onClick={close}>Vzhled</NavLink>}
              <NavLink to="/change-password" onClick={close}>Změnit heslo</NavLink>
              <button className="navbtn" onClick={logout}>Odhlásit</button>
            </div>
          </div>
          <button className="menu-toggle" aria-label="Menu" onClick={() => setMenuOpen((o) => !o)}>
            {menuOpen ? "✕" : "☰"}
          </button>
        </div>
      </header>
      {(() => { const pk = PAGE_BY_PATH[location.pathname]; return pk && !vis(pk)
          ? <main><div className="panel"><p className="muted">Tato stránka není pro tvou roli dostupná.</p></div></main>
          : <Outlet />; })()}
      <Tour open={tour} onClose={() => setTour(false)} />
    </>
  );
}
