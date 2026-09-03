// 📦 Přehled flotily EMSBOXů: spárované (vč. IP) + nespárované ohlášené boxy.
import { useEffect, useState } from "react";
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

export default function Emsboxes() {
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
              <th>Veřejná IP</th><th>Privátní IP</th><th>Síť</th><th>Disk</th><th>RAM</th><th>Buffer</th><th>Drift</th><th>Verze</th></tr></thead>
            <tbody>
              {d.boxes.map((b) => (
                <tr key={b.id} style={rowStyle(b.disk_free_mb)} title={lowDisk(b.disk_free_mb) ? "⚠ méně než 10 GB volného místa" : undefined}>
                  <td>{b.status === "online" ? "🟢" : b.status === "pairing" ? "🟡" : "🔴"}</td>
                  <td><b>{b.name}</b> <span className="muted">#{b.id}</span></td>
                  <td>{b.hostname || "—"}</td>
                  <td>{b.locality_name || b.locality_id}</td>
                  <td>{ago(b.last_heartbeat)}</td>
                  <td>{ago(b.last_ingest)}</td>
                  <td>{b.public_ip || "—"}</td>
                  <td>{b.private_ip ? <a href={`http://${b.private_ip}`} target="_blank" rel="noreferrer">{b.private_ip}</a> : "—"}</td>
                  <td>{b.wifi_ssid ? `📶 ${b.wifi_ssid}` : "🔌 LAN"}</td>
                  <td style={lowDisk(b.disk_free_mb) ? { color: "#f85149", fontWeight: 700 } : {}}>{diskCell(b.disk_total_mb, b.disk_free_mb)}</td>
                  <td>{b.mem_total_mb != null ? `${gb(b.mem_used_mb)} / ${gb(b.mem_total_mb)}` : "—"}</td>
                  <td>{b.buffer_rows ?? "—"} ř.</td>
                  <td style={Math.abs(b.clock_drift_s || 0) > 60 ? { color: "#f85149" } : {}}>{b.clock_drift_s != null ? `${Math.round(b.clock_drift_s)} s` : "—"}</td>
                  <td>{b.agent_version || "—"}</td>
                </tr>))}
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
