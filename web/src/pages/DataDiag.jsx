// 📚 Datová diagnostika portálu — DB, hypertable samples (chunky/komprese/retence), agregát, úlohy Timescale.
import { useEffect, useState } from "react";
import { api } from "../api";

const gb = (b) => (b == null ? "—" : b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(0)} MB` : `${(b / 1e3).toFixed(0)} kB`);
const dt = (iso) => (iso ? new Date(iso).toLocaleString("cs-CZ") : "—");
const ago = (iso) => { if (!iso) return ""; const m = Math.round((Date.now() - new Date(iso)) / 60000);
  return m < 1 ? "právě teď" : m < 60 ? `před ${m} min` : m < 1440 ? `před ${Math.floor(m / 60)} h` : `před ${Math.floor(m / 1440)} d`; };
const JOB_CZ = { policy_compression: "🗜 komprese surových vzorků", policy_retention: "🧹 retence (mazání starých chunků)",
  policy_refresh_continuous_aggregate: "📐 obnova 15min agregátu", policy_reorder: "reorder", policy_recompression: "rekomprese" };

function Section({ title, children, right }) {
  return (<div className="panel" style={{ marginBottom: 14 }}>
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
      <div style={{ fontWeight: 700, fontSize: 14 }}>{title}</div><span style={{ flex: 1 }} />{right}
    </div>{children}</div>);
}

export default function DataDiag() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const load = () => api.dataDiag().then(setD).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  if (err) return <p className="error">{err}</p>;
  if (!d) return <p className="muted">Načítám…</p>;
  const s = d.sizes || {}, c = d.compression || {};
  const chunks = d.chunks || [];
  const compressed = chunks.filter((x) => x.is_compressed).length;
  const oldest = chunks[0], newest = chunks[chunks.length - 1];
  const retention = (d.jobs || []).find((j) => j.proc_name === "policy_retention");
  const compression = (d.jobs || []).find((j) => j.proc_name === "policy_compression");
  const retentionOk = retention && retention.last_run_status === "Success";
  const stale = (d.per_device || []).filter((x) => !x.last_sample || (Date.now() - new Date(x.last_sample)) > 10 * 60000);
  const rawDays = d.raw_range?.raw_from ? Math.round((Date.now() - new Date(d.raw_range.raw_from)) / 86400000) : null;
  return (
    <div>
      <h1 style={{ fontSize: 20, marginTop: 0 }}>📚 Datová diagnostika portálu</h1>
      <Section title="Velikost dat" right={<button className="btn" onClick={load}>↻ obnovit</button>}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10 }}>
          {[["Databáze celkem", gb(s.db_bytes)], ["Surové vzorky (samples)", gb(s.samples_bytes)],
            ["15min agregát", gb(s.agg_bytes)], ["Před kompresí → po", c.before_bytes ? `${gb(c.before_bytes)} → ${gb(c.after_bytes)} (${(c.before_bytes / Math.max(1, c.after_bytes)).toFixed(1)}×)` : "—"],
            ["Řádků za 24 h", d.rows_24h?.toLocaleString("cs-CZ")], ["Surová data od", d.raw_range?.raw_from ? `${dt(d.raw_range.raw_from)} (${rawDays} d)` : "—"],
            ["Agregát od", `${dt(d.agg_range?.agg_from)} · ${Number(d.agg_range?.rows || 0).toLocaleString("cs-CZ")} ř.`],
            ["Spot (OTE)", d.spot?.spot_from ? `${new Date(d.spot.spot_from).toLocaleDateString("cs-CZ")} – ${new Date(d.spot.spot_to).toLocaleDateString("cs-CZ")} · ${Number(d.spot.slots).toLocaleString("cs-CZ")} slotů` : "—"],
          ].map(([k, v]) => (<div key={k} className="card"><div className="label">{k}</div><div className="value" style={{ fontSize: 15 }}>{v ?? "—"}</div></div>))}
        </div>
        <p className="muted" style={{ fontSize: 11.5, margin: "8px 0 0" }}>TimescaleDB {s.timescale} · {String(s.postgres || "").split(" on ")[0]}</p>
      </Section>

      <Section title={`Retence a komprese surových dat · ${compressed}/${chunks.length} chunků komprimováno`}>
        <div style={{ fontSize: 13, marginBottom: 6 }}>
          <div>🧹 Retence: {retention ? <>{retention.last_run_status === "Success" ? "✅" : retention.last_run_status ? "❌" : "⏳ ještě neběžela"} poslední běh {dt(retention.last_run_started_at)}{retention.last_run_status ? ` (${retention.last_run_status})` : ""} · další {dt(retention.next_start)} · pravidlo: smazat chunky starší {(() => { try { return JSON.parse(retention.config).drop_after; } catch (e) { return "?"; } })()}</> : <span className="muted">politika není nastavena</span>}</div>
          <div>🗜 Komprese: {compression ? <>{compression.last_run_status === "Success" ? "✅" : compression.last_run_status ? "❌" : "⏳"} poslední běh {dt(compression.last_run_started_at)} · další {dt(compression.next_start)} · komprimovat starší {(() => { try { return JSON.parse(compression.config).compress_after; } catch (e) { return "?"; } })()}</> : <span className="muted">politika není nastavena</span>}</div>
          <div>Nejstarší surový chunk: <b>{oldest ? new Date(oldest.range_start).toLocaleDateString("cs-CZ") : "—"}</b>{oldest && (Date.now() - new Date(oldest.range_end)) > 97 * 86400000 && <span style={{ color: "var(--amber)" }}> ⚠ starší než 97 dní — retence zřejmě neproběhla</span>}{retentionOk && oldest && (Date.now() - new Date(oldest.range_end)) <= 97 * 86400000 && <span style={{ color: "var(--green)" }}> ✓ odpovídá retenci 3 měsíce</span>}</div>
        </div>
        <details><summary className="muted" style={{ cursor: "pointer", fontSize: 12 }}>chunky ({chunks.length})</summary>
          <table style={{ fontSize: 12, marginTop: 6 }}>
            <thead><tr><th>Od</th><th>Do</th><th>Komprese</th><th>Velikost</th></tr></thead>
            <tbody>{chunks.map((x) => (<tr key={x.chunk_name}><td>{new Date(x.range_start).toLocaleDateString("cs-CZ")}</td><td>{new Date(x.range_end).toLocaleDateString("cs-CZ")}</td><td>{x.is_compressed ? "🗜 ano" : "surový"}</td><td>{x.size}</td></tr>))}</tbody>
          </table></details>
      </Section>

      <Section title="Úlohy TimescaleDB (politiky)">
        <table style={{ fontSize: 12 }}>
          <thead><tr><th>Úloha</th><th>Tabulka</th><th>Interval</th><th>Poslední běh</th><th>Výsledek</th><th>Trvání</th><th>Další start</th><th>Běhů / chyb</th></tr></thead>
          <tbody>{(d.jobs || []).map((j) => (<tr key={j.job_id}>
            <td>{JOB_CZ[j.proc_name] || j.proc_name}</td><td className="muted">{j.hypertable_name || "—"}</td><td>{j.schedule}</td>
            <td>{dt(j.last_run_started_at)}</td>
            <td style={{ color: j.last_run_status === "Success" ? "var(--green)" : j.last_run_status ? "#f85149" : "inherit" }}>{j.last_run_status || "—"}</td>
            <td>{j.last_run_duration || "—"}</td><td>{dt(j.next_start)}</td><td>{j.total_runs ?? "—"} / {j.total_failures ?? "—"}</td></tr>))}</tbody>
        </table>
      </Section>

      <Section title={`Zařízení · ${stale.length ? `${stale.length} bez čerstvých dat` : "všechna hlásí"}`}>
        <table style={{ fontSize: 12 }}>
          <thead><tr><th>ID</th><th>Název</th><th>Adaptér</th><th>Lokalita</th><th>Čte</th><th>Poslední vzorek</th><th>Řádků / 24 h</th></tr></thead>
          <tbody>{(d.per_device || []).map((x) => { const old = !x.last_sample || (Date.now() - new Date(x.last_sample)) > 10 * 60000; return (
            <tr key={x.device_id} style={old ? { color: "#f85149" } : {}}>
              <td style={{ fontFamily: "monospace", fontSize: 11 }}>{x.device_id}</td><td>{x.name}</td><td>{x.adapter}</td><td>{x.locality || "—"}</td>
              <td>{x.emsbox_id ? `📦 EMSBOX #${x.emsbox_id}` : "🖥 server"}</td>
              <td>{x.last_sample ? `${dt(x.last_sample)} (${ago(x.last_sample)})` : "nikdy"}</td><td>{Number(x.rows_24h || 0).toLocaleString("cs-CZ")}</td></tr>); })}</tbody>
        </table>
      </Section>

      <Section title={`Řádky za 24 h po veličinách (${(d.per_metric || []).length} metrik)`}>
        <div style={{ columns: "3 220px", fontSize: 12 }}>
          {(d.per_metric || []).map((m) => (<div key={m.metric} style={{ display: "flex", justifyContent: "space-between", breakInside: "avoid" }}>
            <span style={{ fontFamily: "monospace" }}>{m.metric}</span><span>{Number(m.rows_24h).toLocaleString("cs-CZ")}</span></div>))}
        </div>
      </Section>

      <Section title="Největší tabulky (mimo chunky)">
        <table style={{ fontSize: 12 }}><tbody>{(d.tables || []).map((t) => (<tr key={t.table}><td style={{ fontFamily: "monospace" }}>{t.table}</td><td style={{ textAlign: "right" }}>{t.size}</td></tr>))}</tbody></table>
      </Section>
      <p className="muted" style={{ fontSize: 11.5 }}>Vygenerováno {dt(d.generated_at)}. Retence: surové vzorky 3 měsíce (= aktuální + 2 celé měsíce, mazáno po 7denních chuncích); 15min agregát se nemaže.</p>
    </div>
  );
}
