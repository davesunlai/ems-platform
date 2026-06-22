import { useEffect, useState, useRef } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { api } from "../api";
import Tour, { tourSeen } from "./Tour";

function AlertsBell() {
  const [data, setData] = useState({ count: 0, alerts: [] });
  const [open, setOpen] = useState(false);
  const [pref, setPref] = useState({ notify_email: true, notify_browser: true });
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "unsupported");
  const seen = useRef(null);

  useEffect(() => {
    api.me().then((m) => setPref({ notify_email: m.notify_email !== false, notify_browser: m.notify_browser !== false })).catch(() => {});
    const load = () => api.alerts().then((d) => {
      setData(d);
      // Browser notifikace (jen když je appka otevřená): vypal nové výstrahy.
      const ids = new Set((d.alerts || []).map((a) => a.id));
      if (seen.current === null) { seen.current = ids; return; }   // první načtení neoznamuj
      if (pref.notify_browser && typeof Notification !== "undefined" && Notification.permission === "granted") {
        for (const a of d.alerts || []) {
          if (!seen.current.has(a.id)) {
            try { new Notification(`TERA EMS · ${a.title}`, { body: `${a.locality_name || ""}\n${a.detail || ""}` }); } catch { /* ignore */ }
          }
        }
      }
      seen.current = ids;
    }).catch(() => {});
    load(); const t = setInterval(load, 180000); return () => clearInterval(t);
  }, [pref.notify_browser]);

  const save = (email, browser) => {
    setPref({ notify_email: email, notify_browser: browser });
    api.setNotifyChannels(email, browser).catch(() => {});
  };
  const enableBrowser = async () => {
    if (typeof Notification === "undefined") return;
    const p = await Notification.requestPermission();
    setPerm(p);
    if (p === "granted") save(pref.notify_email, true);
  };

  const count = data.count || 0;
  const triColor = count > 0 ? "var(--amber, #e0a000)" : "var(--text-muted, #6b6b76)";
  const ck = { display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, cursor: "pointer" };
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
            <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted)", marginBottom: 6 }}>Jak chci dostávat upozornění</div>
            <label style={ck}><input type="checkbox" checked={pref.notify_email} onChange={(e) => save(e.target.checked, pref.notify_browser)} /> ✉️ e-mailem</label>
            <label style={{ ...ck, marginTop: 4 }}><input type="checkbox" checked={pref.notify_browser} onChange={(e) => save(pref.notify_email, e.target.checked)} /> 🖥️ v prohlížeči (když je appka otevřená)</label>
            <label style={{ ...ck, marginTop: 4, opacity: 0.5 }}><input type="checkbox" disabled /> 📱 na mobilu (push) — připravujeme</label>
            {pref.notify_browser && perm !== "granted" && perm !== "unsupported" && (
              <button className="btn" style={{ marginTop: 8, padding: "4px 10px", fontSize: 12 }} onClick={enableBrowser}>
                Povolit upozornění v prohlížeči
              </button>
            )}
            {perm === "denied" && <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>Prohlížeč má upozornění zakázaná — povol je v nastavení webu.</div>}
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
          {has("admin") && <NavLink to="/automation">Automatizace</NavLink>}
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
