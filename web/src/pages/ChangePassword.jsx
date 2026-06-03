import { useState } from "react";
import { api } from "../api";

export default function ChangePassword() {
  const [oldp, setOldp] = useState("");
  const [p1, setP1] = useState("");
  const [p2, setP2] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(""); setMsg("");
    if (p1.length < 6) return setErr("Nové heslo musí mít aspoň 6 znaků");
    if (p1 !== p2) return setErr("Nová hesla se neshodují");
    setBusy(true);
    try { await api.changePassword(oldp, p1); setMsg("Heslo změněno."); setOldp(""); setP1(""); setP2(""); }
    catch (e) { setErr(e.message || "Změna selhala"); }
    finally { setBusy(false); }
  };

  return (
    <main>
      <div className="panel" style={{ maxWidth: 460 }}>
        <h3>Změna hesla</h3>
        <div className="field"><label>Současné heslo</label>
          <input type="password" value={oldp} onChange={(e) => setOldp(e.target.value)} /></div>
        <div className="field"><label>Nové heslo</label>
          <input type="password" value={p1} onChange={(e) => setP1(e.target.value)} /></div>
        <div className="field"><label>Nové heslo znovu</label>
          <input type="password" value={p2} onChange={(e) => setP2(e.target.value)} /></div>
        <button className="btn primary" disabled={busy} onClick={submit}>Změnit heslo</button>
        {msg && <p style={{ color: "var(--green)", marginTop: 10 }}>{msg}</p>}
        {err && <p className="error">{err}</p>}
      </div>
    </main>
  );
}
