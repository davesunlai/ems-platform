// 🔬 Diagnostika modulu: dostupnost čtení, díry (komunikace/restart), čerstvost metrik,
// stav na EMSBOXu, timeline povelů. Vše čtené z DB — nesahá na zařízení.
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("cs-CZ") : "—");
const dur = (s) => (s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`
  : s >= 60 ? `${Math.round(s / 60)} min` : `${s} s`);
const age = (iso) => {
  if (!iso) return "—";
  const s = Math.round((Date.now() - new Date(iso)) / 1000);
  return s < 90 ? `před ${s} s` : s < 5400 ? `před ${Math.round(s / 60)} min` : `před ${Math.round(s / 3600)} h`;
};

export default function ModuleDiag() {
  const { id } = useParams();
  const [hours, setHours] = useState(24);
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const load = () => api.moduleDiagnostics(id, hours).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); load(); const t = setInterval(load, 30000); return () => clearInterval(t); /* eslint-disable-next-line */ }, [id, hours]);
  if (err) return <p className="error">{err}</p>;
  if (!d) return <p className="muted">Načítám diagnostiku…</p>;
  const cov = d.coverage; const covColor = cov.pct >= 99 ? "var(--green)" : cov.pct >= 95 ? "var(--amber)" : "#f85149";
  const srcs = d.module.control_sources || {};
  const srcTxt = ["planner", "schedule", "spot"].map((k) => ({ planner: "🧠", schedule: "⏰", spot: "⚡" }[k]
    + (srcs[k] === false ? "✗" : "✓")).replace("✓", "")).join(" ");
  return (
    <div>
      <h1 style={{ fontSize: 20, marginTop: 0 }}>🔬 Diagnostika — {d.module.id}
        <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}> · {d.module.adapter}
          {d.module.emsbox_id ? ` · 📦 box #${d.module.emsbox_id}` : " · přímo (server)"}</span></h1>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        {[6, 24, 72, 168].map((h) => (
          <button key={h} className={h === hours ? "btn primary" : "btn"} style={{ padding: "4px 10px", fontSize: 12 }}
                  onClick={() => setHours(h)}>{h < 48 ? `${h} h` : `${h / 24} dní`}</button>))}
        <span className="muted" style={{ fontSize: 12 }}>auto-obnova à 30 s · <Link to="/control">Řízení</Link> · <Link to="/modules">Moduly</Link></span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(210px,1fr))", gap: 10, marginBottom: 14 }}>
        <div className="panel"><div className="muted" style={{ fontSize: 12 }}>Dostupnost čtení ({d.window_hours} h)</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: covColor }}>{cov.pct} %</div>
          <div className="muted" style={{ fontSize: 12 }}>{cov.samples} vzorků · poslední {age(cov.last)}</div></div>
        <div className="panel"><div className="muted" style={{ fontSize: 12 }}>Výpadky čtení &gt; 2 min</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>{d.gaps.length}</div>
          <div className="muted" style={{ fontSize: 12 }}>komunikace NEBO restart zařízení/boxu</div></div>
        <div className="panel"><div className="muted" style={{ fontSize: 12 }}>Stav řízení</div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>{d.state ? d.state.action : "—"}</div>
          <div className="muted" style={{ fontSize: 12 }}>{d.state ? `${d.state.source || "?"} · od ${fmt(d.state.since)}` : "bez záznamu"}
            <br />zdroje: {srcTxt || "výchozí (vše)"}</div></div>
        {d.box && (
          <div className="panel"><div className="muted" style={{ fontSize: 12 }}>📦 EMSBOX {d.box.name} #{d.box.id}</div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{d.box.status === "online" ? "🟢 online" : `🔴 ${d.box.status}`}</div>
            <div className="muted" style={{ fontSize: 12 }}>
              heartbeat {age(d.box.last_heartbeat)}
              {d.box.device && <><br />{d.box.device.ok ? "🟢 čte" : "🔴 nečte"}
                {d.box.device.via ? ` · ${d.box.device.via}` : ""}
                {d.box.device.error ? ` · ${String(d.box.device.error).slice(0, 60)}` : ""}</>}
            </div></div>)}
      </div>

      <div className="panel" style={{ marginBottom: 14 }}>
        <b style={{ fontSize: 14 }}>Výpadky čtení (od–do, trvání)</b>
        {d.gaps.length ? (
          <table style={{ fontSize: 12.5, marginTop: 6 }}>
            <thead><tr><th>Od</th><th>Do</th><th>Trvání</th></tr></thead>
            <tbody>{d.gaps.map((g, i) => (
              <tr key={i}><td>{fmt(g.od)}</td><td>{fmt(g.do)}</td>
                <td style={g.trvani_s > 600 ? { color: "#f85149", fontWeight: 700 } : {}}>{dur(g.trvani_s)}</td></tr>))}
            </tbody></table>
        ) : <p className="muted" style={{ margin: "6px 0 0" }}>Žádné díry — čtení běželo nepřetržitě. 👌</p>}
      </div>

      <div className="panel" style={{ marginBottom: 14 }}>
        <b style={{ fontSize: 14 }}>Čerstvost metrik</b>
        <table style={{ fontSize: 12.5, marginTop: 6 }}>
          <thead><tr><th>Metrika</th><th>Poslední hodnota</th><th>Stáří</th></tr></thead>
          <tbody>{d.metrics.map((m) => {
            const old = (Date.now() - new Date(m.time)) / 1000 > 300;
            return (<tr key={m.metric}>
              <td>{m.metric}</td>
              <td>{Math.round(m.value * 100) / 100}</td>
              <td style={old ? { color: "var(--amber)" } : {}}>{age(m.time)}{old ? " ⚠" : ""}</td></tr>);
          })}</tbody></table>
      </div>

      <div className="panel">
        <b style={{ fontSize: 14 }}>Timeline povelů (posledních 30)</b>
        {d.commands.length ? (
          <table style={{ fontSize: 12, marginTop: 6 }}>
            <thead><tr><th>#</th><th>Čas</th><th>Povel</th><th>Zdroj</th><th>Stav</th><th>Latence</th><th>Důvod / výsledek</th></tr></thead>
            <tbody>{d.commands.map((c) => (
              <tr key={c.id}>
                <td className="muted">{c.id}</td><td>{fmt(c.created_at)}</td>
                <td><b>{c.action}</b></td><td>{c.source || c.username || "—"}</td>
                <td style={c.status !== "done" ? { color: "var(--amber)" } : {}}>{c.status}</td>
                <td>{c.latence_s != null ? `${c.latence_s} s` : "—"}</td>
                <td className="muted" style={{ maxWidth: 380, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={(c.reason || "") + " " + (c.result_short || "")}>{c.reason || c.result_short || "—"}</td>
              </tr>))}
            </tbody></table>
        ) : <p className="muted" style={{ margin: "6px 0 0" }}>Žádné povely.</p>}
        <p className="muted" style={{ fontSize: 11.5, marginBottom: 0 }}>
          Prázdná timeline + přesto se měnící chování měniče = zásah PŘICHÁZÍ ODJINUD (interní funkce měniče, SolisCloud, displej).
        </p>
      </div>
    </div>
  );
}
