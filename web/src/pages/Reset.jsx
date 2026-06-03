import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";

export default function Reset() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const nav = useNavigate();
  const [p1, setP1] = useState("");
  const [p2, setP2] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr("");
    if (p1.length < 6) return setErr("Heslo musí mít aspoň 6 znaků");
    if (p1 !== p2) return setErr("Hesla se neshodují");
    setBusy(true);
    try { await api.resetPassword(token, p1); setOk(true); setTimeout(() => nav("/login"), 1800); }
    catch (e) { setErr(e.message || "Reset selhal"); }
    finally { setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="brand"><span className="dot" /><b>Nové heslo</b></div>
        {!token ? (
          <p className="error">Chybí token. Otevři odkaz z e-mailu.</p>
        ) : ok ? (
          <p className="muted">Heslo nastaveno. Přesměrovávám na přihlášení…</p>
        ) : (
          <>
            <div className="field"><label>Nové heslo</label>
              <input type="password" value={p1} autoFocus onChange={(e) => setP1(e.target.value)} /></div>
            <div className="field"><label>Heslo znovu</label>
              <input type="password" value={p2} onChange={(e) => setP2(e.target.value)}
                     onKeyDown={(e) => e.key === "Enter" && submit()} /></div>
            <button className="btn primary full" disabled={busy} onClick={submit}>
              {busy ? "Ukládám…" : "Nastavit heslo"}
            </button>
            <p className="error">{err}</p>
          </>
        )}
        <p style={{ textAlign: "center", marginTop: 8 }}>
          <Link to="/login" className="muted" style={{ fontSize: 13 }}>Zpět na přihlášení</Link>
        </p>
      </div>
    </div>
  );
}
