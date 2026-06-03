import { useEffect, useState } from "react";
import { api } from "../api";

export default function Ewelink() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true); setErr("");
    api.ewelinkDevices().then(setData).catch((e) => setErr(e.message)).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  return (
    <main>
      <div className="panel">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h3 style={{ margin: 0 }}>eWeLink / Sonoff — test připojení</h3>
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={load} disabled={loading}>{loading ? "Načítám…" : "Obnovit"}</button>
        </div>

        {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}

        {data && !data.configured && (
          <p className="muted" style={{ marginTop: 12 }}>
            eWeLink není nakonfigurován. Doplň do <code>.env</code> na serveru:
            <code style={{ display: "block", marginTop: 6, whiteSpace: "pre", fontSize: 12 }}>
{`EMS_EWELINK_APPID=...
EMS_EWELINK_SECRET=...
EMS_EWELINK_EMAIL=...
EMS_EWELINK_PASSWORD=...
EMS_EWELINK_REGION=eu
EMS_EWELINK_COUNTRY=+420`}
            </code>
            App ID a Secret získáš na dev.ewelink.cc, e-mail/heslo je tvůj eWeLink účet.
          </p>
        )}

        {data && data.configured && (
          <table style={{ marginTop: 14 }}>
            <thead><tr><th>Stav</th><th>Název</th><th>Device ID</th><th>Vypínač</th><th>Příkon</th><th>Napětí</th><th>Proud</th></tr></thead>
            <tbody>
              {data.devices.map((d) => (
                <tr key={d.deviceid}>
                  <td><span className="dot" style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: d.online ? "var(--green)" : "#e06c75" }} title={d.online ? "online" : "offline"} /></td>
                  <td>{d.name || "—"}</td>
                  <td className="role" style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{d.deviceid}</td>
                  <td>{d.switch ? <span className={d.switch === "on" ? "badge-on" : "badge-off"}>{d.switch}</span> : "—"}</td>
                  <td className="muted">{d.power != null ? `${d.power} W` : "—"}</td>
                  <td className="muted">{d.voltage != null ? `${d.voltage} V` : "—"}</td>
                  <td className="muted">{d.current != null ? `${d.current} A` : "—"}</td>
                </tr>
              ))}
              {!data.devices.length && <tr><td colSpan="7" className="muted">Účet nemá žádná zařízení.</td></tr>}
            </tbody>
          </table>
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 14 }}>
          Test ověřuje připojení a čtení z eWeLink cloudu. Ovládání (on/off) a telemetrii na dashboard navážeme po potvrzení, že výpis funguje.
        </p>
      </div>
    </main>
  );
}
