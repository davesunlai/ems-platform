// 📦 Přehled flotily EMSBOXů: spárované (vč. IP) + nespárované ohlášené boxy.
import React, { useEffect, useState } from "react";
import BoxConsole from "../components/BoxConsole";
import { useAuth } from "../auth";
import { api } from "../api";

const gb = (mb) => (mb == null ? "—" : (mb / 1000).toFixed(mb < 10000 ? 1 : 0) + " GB");
const diskCell = (total, free) => (total == null ? "—" : `${gb(total - free)} / ${gb(total)} · volno ${gb(free)}`);
const lowDisk = (free) => free != null && free < 10000;   // < 10 GB
const rowStyle = (free) => (lowDisk(free) ? { background: "rgba(248,81,73,.12)" } : undefined);

const ago = (iso) => {
  if (!iso) return "nikdy";
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 1 ? "právě teď" : m < 60 ? `před ${m} min` : m < 1440 ? `před ${Math.floor(m / 60)} h` : `před ${Math.floor(m / 1440)} d`;
};

const ACTION_CZ = { update_agent: "update agenta", reset_localui_password: "reset hesla UI" };
const ACTION_CZ_DYN = (a) => (a && a.startsWith("open_console") ? "servisní konzole" : ACTION_CZ[a] || a);

function ActionStatus({ box }) {
  const a = ACTION_CZ_DYN(box.last_action);
  const t = box.last_action_at ? new Date(box.last_action_at).toLocaleString("cs-CZ") : "";
  const S = {
    pending:   { ico: "⏳", txt: `zadán pokyn: ${a} — čeká na vyzvednutí boxem`, col: "var(--amber)" },
    delivered: { ico: "📨", txt: `pokyn ${a} předán boxu — provádí se…`, col: "var(--blue, #58a6ff)" },
    done:      { ico: "✅", txt: `${a}: úspěšně provedeno${box.last_action_detail ? ` (${box.last_action_detail})` : ""}`, col: "var(--green)" },
    failed:    { ico: "❌", txt: `${a}: selhalo${box.last_action_detail ? ` — ${box.last_action_detail}` : ""}`, col: "#f85149" },
  }[box.last_action_status] || { ico: "•", txt: a, col: "var(--muted)" };
  const [hist, setHist] = useState(null);
  const toggle = async () => {
    if (hist) { setHist(null); return; }
    try { setHist((await api.emsboxActions(box.id)).actions); } catch (e) { alert(e.message); }
  };
  return (<>
    <span style={{ color: S.col }}>{S.ico} {S.txt}
      {box.last_action_username && <span className="muted"> · zadal {box.last_action_username}</span>}
      <span className="muted"> · {t}</span>{" "}
      <span style={{ cursor: "pointer" }} className="muted" onClick={toggle}
            title="historie servisních akcí">📜 {hist ? "skrýt" : "historie"}</span>
    </span>
    {hist && (
      <table style={{ fontSize: 11.5, marginTop: 4 }}>
        <thead><tr><th>Kdy</th><th>Akce</th><th>Zadal</th><th>Stav</th><th>Detail</th></tr></thead>
        <tbody>{hist.map((h) => (
          <tr key={h.id}>
            <td>{new Date(h.created_at).toLocaleString("cs-CZ")}</td>
            <td>{ACTION_CZ_DYN(h.action)}</td>
            <td>{h.username || "—"}</td>
            <td>{{ pending: "⏳", delivered: "📨", done: "✅", failed: "❌" }[h.status] || h.status}</td>
            <td className="muted">{h.detail || ""}</td>
          </tr>))}
        </tbody></table>)}
  </>);
}

function UpdateBtn({ box }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (!window.confirm(`Aktualizovat agenta boxu „${box.name || box.id}"?\n` +
        "Box provede git pull + rebuild + restart (~3 min); čtení se na tu dobu přeruší (buffer nic neztratí).")) return;
    setBusy(true);
    try { await api.emsboxUpdateAgent(box.id); alert("Požadavek odeslán — po dokončení se ve fleetu objeví nová verze."); }
    catch (e) { alert("Chyba: " + e.message); }
    setBusy(false);
  };
  return <button className="btn" disabled={busy} title="Dálkový update agenta (git pull + rebuild)"
                 style={{ padding: "2px 7px", fontSize: 11.5, marginLeft: 4 }} onClick={go}>⬆ update</button>;
}

function ConsoleBtn({ box }) {
  const [open, setOpen] = useState(false);
  return (<>
    <button className="btn" title="Servisní konzole boxu (shell agenta)"
            style={{ padding: "3px 8px", fontSize: 12, marginRight: 6 }} onClick={() => setOpen(true)}>🖥 konzole</button>
    {open && <BoxConsole box={box} onClose={() => setOpen(false)} />}
  </>);
}

function ResetUiPw({ box }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (!window.confirm(`Resetovat uživatelské heslo lokálního UI boxu „${box.name || box.id}"?\n` +
        "Box si akci vyzvedne do ~30 s; UI pak nabídne založení nového hesla. (Servisní topadmin heslo se nemění.)")) return;
    setBusy(true);
    try { await api.emsboxResetUiPassword(box.id); alert("Požadavek odeslán — box ho vyzvedne s příštím heartbeatem."); }
    catch (e) { alert("Chyba: " + e.message); }
    setBusy(false);
  };
  return <button className="btn" disabled={busy} title="Reset uživatelského hesla lokálního UI"
                 style={{ padding: "3px 8px", fontSize: 12 }} onClick={go}>🔐 reset hesla UI</button>;
}

function Psk({ value }) {
  const [show, setShow] = useState(false);
  return (
    <span className="muted" style={{ marginLeft: 6, fontSize: 12 }}>
      🔑 <span style={{ fontFamily: "monospace" }}>{show ? value : "••••••"}</span>{" "}
      <span style={{ cursor: "pointer" }} title={show ? "skrýt" : "zobrazit heslo Wi-Fi"}
            onClick={() => setShow(!show)}>{show ? "🙈" : "👁"}</span>
    </span>
  );
}

export default function Emsboxes() {
  const { vis } = useAuth();
  const [d, setD] = useState({ boxes: [], unpaired: [] });
  const [err, setErr] = useState("");
  const load = () => api.emsboxOverview().then(setD).catch((e) => setErr(e.message));
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, []);
  return (
    <div>
      <h1 style={{ fontSize: 20, marginTop: 0 }}>📦 EMSBOXy</h1>
      {err && <p className="error">{err}</p>}
      <div className="panel" style={{ marginBottom: 16 }}>
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8 }}>Spárované boxy ({d.boxes.length})</div>
        {d.boxes.length ? (
          <table style={{ fontSize: 12.5 }}>
            <thead><tr><th></th><th>Box</th><th>Hostname</th><th>Lokalita</th><th>Heartbeat</th><th>Ingest</th>
              <th>Veřejná IP</th><th>Privátní IP</th><th>Síť</th><th>Disk</th><th>RAM</th><th>Buffer</th><th>Drift</th><th>Verze</th><th></th></tr></thead>
            <tbody>
              {d.boxes.map((b) => (
                <React.Fragment key={b.id}>
                <tr style={rowStyle(b.disk_free_mb)} title={lowDisk(b.disk_free_mb) ? "⚠ méně než 10 GB volného místa" : undefined}>
                  <td>{b.status === "online" ? "🟢" : b.status === "pairing" ? "🟡" : "🔴"}</td>
                  <td><b>{b.name}</b> <span className="muted">#{b.id}</span></td>
                  <td>{b.hostname || "—"}</td>
                  <td>{b.locality_name || b.locality_id}</td>
                  <td>{ago(b.last_heartbeat)}</td>
                  <td>{ago(b.last_ingest)}</td>
                  <td>{b.public_ip || "—"}</td>
                  <td>{b.private_ip ? <a href={`http://${b.private_ip}`} target="_blank" rel="noreferrer">{b.private_ip}</a> : "—"}</td>
                  <td>{b.wifi_ssid ? `📶 ${b.wifi_ssid}` : "🔌 LAN"}
                      {vis("box:psk") && b.wifi_psk && <Psk value={b.wifi_psk} />}</td>
                  <td style={lowDisk(b.disk_free_mb) ? { color: "#f85149", fontWeight: 700 } : {}}>{diskCell(b.disk_total_mb, b.disk_free_mb)}</td>
                  <td>{b.mem_total_mb != null ? `${gb(b.mem_used_mb)} / ${gb(b.mem_total_mb)}` : "—"}</td>
                  <td>{b.buffer_rows ?? "—"} ř.</td>
                  <td style={Math.abs(b.clock_drift_s || 0) > 60 ? { color: "#f85149" } : {}}>{b.clock_drift_s != null ? `${Math.round(b.clock_drift_s)} s` : "—"}</td>
                  <td>{b.agent_version || "—"} {vis("box:actions") && <UpdateBtn box={b} />}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{vis("box:actions") && <><ConsoleBtn box={b} /><ResetUiPw box={b} /></>}</td>
                </tr>
                {b.last_action && <tr>
                  <td colSpan={99} style={{ paddingTop: 0, fontSize: 12 }}><ActionStatus box={b} /></td>
                </tr>}
                </React.Fragment>))}
            </tbody>
          </table>
        ) : <p className="muted">Zatím žádné boxy.</p>}
        <p className="muted" style={{ fontSize: 11.5, marginBottom: 0 }}>
          Privátní IP je klikací — otevře lokální UI boxu (funguje jen ze stejné sítě jako box).
        </p>
      </div>
      <div className="panel">
        <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8 }}>
          Zapnuté, ale nespárované boxy ({d.unpaired.length})
        </div>
        {d.unpaired.length ? (
          <table style={{ fontSize: 12.5 }}>
            <thead><tr><th>Otisk HW</th><th>Hostname</th><th>Veřejná IP</th><th>Privátní IP</th><th>Síť</th><th>Disk</th><th>RAM</th><th>Verze</th><th>Poprvé</th><th>Naposledy</th></tr></thead>
            <tbody>
              {d.unpaired.map((u) => { const h = u.hw || {}; return (
                <tr key={u.fingerprint} style={rowStyle(h.disk_free_mb)} title={lowDisk(h.disk_free_mb) ? "⚠ méně než 10 GB volného místa" : undefined}>
                  <td style={{ fontFamily: "monospace", fontSize: 11 }}>{u.fingerprint.slice(0, 18)}…</td>
                  <td>{h.hostname || "—"}</td>
                  <td>{u.public_ip || "—"}</td>
                  <td>{u.private_ip ? <a href={`http://${u.private_ip}`} target="_blank" rel="noreferrer">{u.private_ip}</a> : "—"}</td>
                  <td>{h.wifi_ssid ? `📶 ${h.wifi_ssid}` : "🔌 LAN"}</td>
                  <td style={lowDisk(h.disk_free_mb) ? { color: "#f85149", fontWeight: 700 } : {}}>{diskCell(h.disk_total_mb, h.disk_free_mb)}</td>
                  <td>{h.mem_total_mb != null ? `${gb(h.mem_used_mb)} / ${gb(h.mem_total_mb)}` : "—"}</td>
                  <td>{u.agent_version || "—"}</td>
                  <td>{ago(u.first_seen)}</td>
                  <td>{ago(u.last_seen)}</td>
                </tr>); })}
            </tbody>
          </table>
        ) : <p className="muted">Žádný nespárovaný box se za posledních 10 minut neohlásil.</p>}
        <p className="muted" style={{ fontSize: 11.5, marginBottom: 0 }}>
          Nespárovaný box se hlásí sám po zapnutí (à 60 s). Heslo Wi-Fi se z bezpečnostních důvodů nikam neposílá — zůstává jen na boxu. Spáruješ ho: Lokality → „+ Přidat EMSBOX" → kód → lokální UI boxu (privátní IP).
        </p>
      </div>
    </div>
  );
}
