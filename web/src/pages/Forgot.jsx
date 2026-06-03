import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

export default function Forgot() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try { await api.forgotPassword(email); } catch { /* záměrně tiše */ }
    finally { setBusy(false); setDone(true); }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="brand"><span className="dot" /><b>Obnova hesla</b></div>
        {done ? (
          <>
            <p className="muted">Pokud e-mail v systému existuje, poslali jsme na něj odkaz pro nastavení nového hesla (platí 1 hodinu).</p>
            <Link to="/login" className="btn full" style={{ textAlign: "center" }}>Zpět na přihlášení</Link>
          </>
        ) : (
          <>
            <div className="field">
              <label>E-mail účtu</label>
              <input value={email} autoFocus onChange={(e) => setEmail(e.target.value)}
                     onKeyDown={(e) => e.key === "Enter" && submit()} />
            </div>
            <button className="btn primary full" disabled={busy || !email} onClick={submit}>
              {busy ? "Odesílám…" : "Poslat odkaz pro obnovu"}
            </button>
            <p style={{ textAlign: "center", marginTop: 8 }}>
              <Link to="/login" className="muted" style={{ fontSize: 13 }}>Zpět na přihlášení</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
