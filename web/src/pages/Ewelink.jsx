import { useEffect, useState } from "react";
import { api } from "../api";

export default function Ewelink() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");

  const load = () => {
    setLoading(true); setErr("");
    api.ewelinkDevices().then(setData).catch((e) => setErr(e.message)).finally(() => setLoading(false));
  };
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("ewelink");
    if (q === "connected") setMsg("eWeLink připojen.");
    if (q === "error") setErr("Připojení eWeLink se nezdařilo, zkus to prosím znovu.");
    if (q) window.history.replaceState({}, "", "/ewelink");
    load();
  }, []);

  const connect = async () => {
    try { const r = await api.ewelinkAuthUrl(); window.location.href = r.url; }
    catch (e) { setErr(e.message); }
  };

  const toggle = async (d) => {
    setBusy(d.deviceid); setErr("");
    try { await api.ewelinkSwitch(d.deviceid, d.switch !== "on"); setTimeout(load, 800); }
    catch (e) { setErr(e.message); }
    finally { setBusy(""); }
  };

  return (
    <main>
      <div className="panel">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h3 style={{ margin: 0 }}>eWeLink / Sonoff</h3>
          {data?.connected && <span className="badge-on">připojeno</span>}
          <span style={{ flex: 1 }} />
          {data?.configured && (
            <button className="btn primary" onClick={connect}>
              {data.connected ? "Připojit znovu" : "Připojit eWeLink"}
            </button>
          )}
          <button className="btn" onClick={load} disabled={loading}>{loading ? "Načítám…" : "Obnovit"}</button>
        </div>

        {msg && <p className="muted" style={{ marginTop: 12 }}>{msg}</p>}
        {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}

        {data && !data.configured && (
          <p className="muted" style={{ marginTop: 12 }}>
            eWeLink není nakonfigurován. Doplň do <code>.env</code> na serveru <code>EMS_EWELINK_APPID</code>,
            <code> EMS_EWELINK_SECRET</code> a případně <code>EMS_EWELINK_REGION</code> (z dev.ewelink.cc).
          </p>
        )}

        {data && data.configured && !data.connected && (
          <p className="muted" style={{ marginTop: 12 }}>
            Účet eWeLink ještě není propojený. Klikni na <strong>Připojit eWeLink</strong>, přihlas se na stránce
            eWeLink a povol přístup — pak se sem vrátíš a zařízení se načtou.
          </p>
        )}

        {data && data.connected && (
          <table style={{ marginTop: 14 }}>
            <thead><tr><th>Stav</th><th>Název</th><th>Device ID</th><th>Vypínač</th><th>Příkon</th><th>Napětí</th><th>Proud</th></tr></thead>
            <tbody>
              {data.devices.map((d) => (
                <tr key={d.deviceid}>
                  <td><span style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: d.online ? "var(--green)" : "#e06c75" }} title={d.online ? "online" : "offline"} /></td>
                  <td>{d.name || "—"}</td>
                  <td className="role" style={{ fontFamily: "var(--mono)", fontSize: 12 }}>{d.deviceid}</td>
                  <td>
                    {d.switch ? (
                      <button className="btn" disabled={!d.online || busy === d.deviceid}
                        onClick={() => toggle(d)} style={{ padding: "2px 10px" }}
                        title={d.online ? "Přepnout" : "Zařízení je offline"}>
                        <span className={d.switch === "on" ? "badge-on" : "badge-off"}>{d.switch}</span>
                        <span style={{ marginLeft: 6, opacity: 0.7 }}>{busy === d.deviceid ? "…" : (d.switch === "on" ? "→ vyp" : "→ zap")}</span>
                      </button>
                    ) : "—"}
                  </td>
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
          Připojení přes OAuth2 — heslo k eWeLink se nikam neukládá, drží se jen přístupový token (sám se obnovuje).
          Napojení Sonoffů na automatizaci (spínání dle spotu/přebytku) přidáme dál.
        </p>
      </div>
    </main>
  );
}
