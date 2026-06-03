import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(""); setBusy(true);
    try { await login(u, p); nav("/"); }
    catch (e) { setErr(e.message || "Přihlášení selhalo"); }
    finally { setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="brand">
          <span className="dot" /><b>TERA EMS</b>
        </div>
        <div className="field">
          <label>Uživatel</label>
          <input value={u} autoFocus onChange={(e) => setU(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && submit()} />
        </div>
        <div className="field">
          <label>Heslo</label>
          <input type="password" value={p} onChange={(e) => setP(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && submit()} />
        </div>
        <button className="btn primary full" disabled={busy} onClick={submit}>
          {busy ? "Přihlašuji…" : "Přihlásit"}
        </button>
        <p className="error">{err}</p>
        <p style={{ textAlign: "center", marginTop: 4 }}>
          <Link to="/forgot" className="muted" style={{ fontSize: 13 }}>Zapomenuté heslo?</Link>
        </p>
      </div>
    </div>
  );
}
