// 📦 Přehled flotily EMSBOXů: spárované (vč. IP) + nespárované ohlášené boxy.
import { useEffect, useState } from "react";
import { api } from "../api";

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
            <thead><tr><th></th><th>Box</th><th>Lokalita</th><th>Heartbeat</th><th>Ingest</th>
              <th>Veřejná IP</th><th>Privátní IP</th><th>Buffer</th><th>Drift</th><th>Verze</th></tr></thead>
            <tbody>
              {d.boxes.map((b) => (
                <tr key={b.id}>
                  <td>{b.status === "online" ? "🟢" : b.status === "pairing" ? "🟡" : "🔴"}</td>
                  <td><b>{b.name}</b> <span className="muted">#{b.id}</span></td>
                  <td>{b.locality_name || b.locality_id}</td>
                  <td>{ago(b.last_heartbeat)}</td>
                  <td>{ago(b.last_ingest)}</td>
                  <td>{b.public_ip || "—"}</td>
                  <td>{b.private_ip ? <a href={`http://${b.private_ip}`} target="_blank" rel="noreferrer">{b.private_ip}</a> : "—"}</td>
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
            <thead><tr><th>Otisk HW</th><th>Veřejná IP</th><th>Privátní IP</th><th>Verze</th><th>Poprvé</th><th>Naposledy</th></tr></thead>
            <tbody>
              {d.unpaired.map((u) => (
                <tr key={u.fingerprint}>
                  <td style={{ fontFamily: "monospace", fontSize: 11 }}>{u.fingerprint.slice(0, 18)}…</td>
                  <td>{u.public_ip || "—"}</td>
                  <td>{u.private_ip ? <a href={`http://${u.private_ip}`} target="_blank" rel="noreferrer">{u.private_ip}</a> : "—"}</td>
                  <td>{u.agent_version || "—"}</td>
                  <td>{ago(u.first_seen)}</td>
                  <td>{ago(u.last_seen)}</td>
                </tr>))}
            </tbody>
          </table>
        ) : <p className="muted">Žádný nespárovaný box se za posledních 10 minut neohlásil.</p>}
        <p className="muted" style={{ fontSize: 11.5, marginBottom: 0 }}>
          Nespárovaný box se hlásí sám po zapnutí (à 60 s). Spáruješ ho: Lokality → „+ Přidat EMSBOX" → kód → lokální UI boxu (privátní IP).
        </p>
      </div>
    </div>
  );
}
