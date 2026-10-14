// 📦 Přehled flotily EMSBOXů: spárované (vč. IP) + nespárované ohlášené boxy.
import React, { useEffect, useState } from "react";
import BoxConsole from "../components/BoxConsole";
import { useAuth } from "../auth";
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

const ACTION_CZ = { update_agent: "update agenta", reset_localui_password: "reset hesla UI" };
const ACTION_CZ_DYN = (a) => (a && a.startsWith("open_console") ? "servisní konzole" : ACTION_CZ[a] || a);

function ActionStatus({ box }) {
  const a = ACTION_CZ_DYN(box.last_action);
  const t = box.last_action_at ? new Date(box.last_action_at).toLocaleString("cs-CZ") : "";
  const S = {
    pending:   { ico: "⏳", txt: `zadán pokyn: ${a} — čeká na vyzvednutí boxem`, col: "var(--amber)" },
    delivered: { ico: "📨", txt: `pokyn ${a} předán boxu — provádí se…`, col: "var(--blue, #58a6ff)" },
    done:      { ico: "✅", txt: `${a}: úspěšně provedeno${box.last_action_detail ? ` (${box.last_action_detail})` : ""}`, col: "var(--green)" },
    failed:    { ico: "❌", txt: `${a}: selhalo${box.last_action_detail ? ` — ${box.last_action_detail}` : ""}`, col: "#f85149" },
  }[box.last_action_status] || { ico: "•", txt: a, col: "var(--muted)" };
  const [hist, setHist] = useState(null);
  const toggle = async () => {
    if (hist) { setHist(null); return; }
    try { setHist((await api.emsboxActions(box.id)).actions); } catch (e) { alert(e.message); }
  };
  return (<>
    <span style={{ color: S.col }}>{S.ico} {S.txt}
      {box.last_action_username && <span className="muted"> · zadal {box.last_action_username}</span>}
      <span className="muted"> · {t}</span>{" "}
      <span style={{ cursor: "pointer" }} className="muted" onClick={toggle}
            title="historie servisních akcí">📜 {hist ? "skrýt" : "historie"}</span>
    </span>
    {hist && (
      <table style={{ fontSize: 11.5, marginTop: 4 }}>
        <thead><tr><th>Kdy</th><th>Akce</th><th>Zadal</th><th>Stav</th><th>Detail</th></tr></thead>
        <tbody>{hist.map((h) => (
          <tr key={h.id}>
            <td>{new Date(h.created_at).toLocaleString("cs-CZ")}</td>
            <td>{ACTION_CZ_DYN(h.action)}</td>
            <td>{h.username || "—"}</td>
            <td>{{ pending: "⏳", delivered: "📨", done: "✅", failed: "❌" }[h.status] || h.status}</td>
            <td className="muted">{h.detail || ""}</td>
          </tr>))}
        </tbody></table>)}
  </>);
}

function UpdateBtn({ box }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (!window.confirm(`Aktualizovat agenta boxu „${box.name || box.id}"?\n` +
        "Box provede git pull + rebuild + restart (~3 min); čtení se na tu dobu přeruší (buffer nic neztratí).")) return;
    setBusy(true);
    try { await api.emsboxUpdateAgent(box.id); alert("Požadavek odeslán — po dokončení se ve fleetu objeví nová verze."); }
    catch (e) { alert("Chyba: " + e.message); }
    setBusy(false);
  };
  return <button className="btn" disabled={busy} title="Dálkový update agenta (git pull + rebuild)"
                 style={{ padding: "2px 7px", fontSize: 11.5, marginLeft: 4 }} onClick={go}>⬆ update</button>;
}

function ConsoleBtn({ box }) {
  const [open, setOpen] = useState(false);
  return (<>
    <button className="btn" title="Servisní konzole boxu (shell agenta)"
            style={{ padding: "3px 8px", fontSize: 12, marginRight: 6 }} onClick={() => setOpen(true)}>🖥 konzole</button>
    {open && <BoxConsole box={box} onClose={() => setOpen(false)} />}
  </>);
}

function ResetUiPw({ box }) {
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (!window.confirm(`Resetovat uživatelské heslo lokálního UI boxu „${box.name || box.id}"?\n` +
        "Box si akci vyzvedne do ~30 s; UI pak nabídne založení nového hesla. (Servisní topadmin heslo se nemění.)")) return;
    setBusy(true);
    try { await api.emsboxResetUiPassword(box.id); alert("Požadavek odeslán — box ho vyzvedne s příštím heartbeatem."); }
    catch (e) { alert("Chyba: " + e.message); }
    setBusy(false);
  };
  return <button className="btn" disabled={busy} title="Reset uživatelského hesla lokálního UI"
                 style={{ padding: "3px 8px", fontSize: 12 }} onClick={go}>🔐 reset hesla UI</button>;
}

function Psk({ value }) {
  const [show, setShow] = useState(false);
  return (
    <span className="muted" style={{ marginLeft: 6, fontSize: 12 }}>
      🔑 <span style={{ fontFamily: "monospace" }}>{show ? value : "••••••"}</span>{" "}
      <span style={{ cursor: "pointer" }} title={show ? "skrýt" : "zobrazit heslo Wi-Fi"}
            onClick={() => setShow(!show)}>{show ? "🙈" : "👁"}</span>
    </span>
  );
}

// --- 🔎 Detail boxu -----------------------------------------------------------
const dt = (iso) => (iso ? new Date(iso).toLocaleString("cs-CZ") : "—");
const dur = (s) => {
  if (s == null || isNaN(s)) return "—";
  s = Math.round(s);
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${s % 60} s`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
  return `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h`;
};
const secs = (a, b) => (a && b ? (new Date(b) - new Date(a)) / 1000 : null);
const num = (n) => (n == null ? "—" : Number(n).toLocaleString("cs-CZ"));
const ALERT_CZ = { offline: "offline", fault: "chyba čtení", rtc_drift: "posun hodin", buffer_high: "plný buffer" };

function KV({ rows }) {
  return (
    <table style={{ fontSize: 12.5 }}><tbody>
      {rows.filter(([, v]) => v !== undefined).map(([k, v]) => (
        <tr key={k}><td className="muted" style={{ whiteSpace: "nowrap", paddingRight: 12 }}>{k}</td><td>{v ?? "—"}</td></tr>))}
    </tbody></table>);
}

function Section({ title, children }) {
  return (<div style={{ marginTop: 14 }}>
    <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 6, borderBottom: "1px solid var(--border, #30363d)", paddingBottom: 3 }}>{title}</div>
    {children}
  </div>);
}

function BoxDetail({ box, onClose }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [raw, setRaw] = useState(false);
  useEffect(() => {
    const load = () => api.emsboxDetail(box.id).then(setD).catch((e) => setErr(e.message));
    load(); const t = setInterval(load, 30000); return () => clearInterval(t);
  }, [box.id]);
  const b = d?.box || {};
  const hb = b.last_heartbeat_body || {};
  const es = d?.episodes_summary || {};
  const st = d?.sync_stats || {};
  const openEp = (d?.episodes || []).find((e) => !e.ended_at);
  const online = b.last_heartbeat && (Date.now() - new Date(b.last_heartbeat)) < 3 * 60000;
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 95, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} className="panel"
           style={{ width: "min(960px, 96vw)", maxHeight: "92vh", overflow: "auto", padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 700, fontSize: 16 }}>🔎 {b.name || box.name} <span className="muted">#{box.id}</span>
            {" "}<span style={{ fontSize: 12, color: online ? "var(--green)" : "#f85149" }}>{online ? "● online" : "● offline"}</span></div>
          <div><span className="muted" style={{ cursor: "pointer", fontSize: 12, marginRight: 12 }} onClick={() => setRaw(!raw)}>{raw ? "skrýt" : "surový"} heartbeat</span>
               <button className="btn" onClick={onClose}>✕ zavřít</button></div>
        </div>
        {err && <p className="error">{err}</p>}
        {!d && !err && <p className="muted">načítám…</p>}
        {d && (<>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
            <Section title="Identita">
              <KV rows={[
                ["Lokalita", b.locality_name || b.locality_id],
                ["Stav", b.status],
                ["Hostname", b.hostname],
                ["Spárováno", dt(b.created_at)],
                ["Verze agenta", b.agent_version],
                ["Běží od startu", dur(b.uptime_s)],
                ["Otisk HW", hb.fingerprint ? <span style={{ fontFamily: "monospace", fontSize: 11 }}>{hb.fingerprint}</span> : null],
                ...(b.hw_info && Object.keys(b.hw_info).length ? Object.entries(b.hw_info).map(([k, v]) => [`HW · ${k}`, typeof v === "object" ? JSON.stringify(v) : String(v)]) : []),
              ]} />
            </Section>
            <Section title="Síť">
              <KV rows={[
                ["Veřejná IP", b.public_ip],
                ["Privátní IP", b.private_ip ? <a href={`http://${b.private_ip}`} target="_blank" rel="noreferrer">{b.private_ip}</a> : null],
                ["Připojení", b.wifi_ssid ? `📶 Wi-Fi „${b.wifi_ssid}"` : "🔌 LAN"],
                ["Poslední heartbeat", `${dt(b.last_heartbeat)} (${ago(b.last_heartbeat)})`],
                ["Poslední ingest", `${dt(b.last_ingest)} (${ago(b.last_ingest)})`],
                ["Posun hodin", b.clock_drift_s != null ? `${Math.round(b.clock_drift_s)} s` : null],
              ]} />
            </Section>
            <Section title="Systém">
              <KV rows={[
                ["Disk", diskCell(b.disk_total_mb, b.disk_free_mb)],
                ["RAM", b.mem_total_mb != null ? `${gb(b.mem_used_mb)} / ${gb(b.mem_total_mb)}` : null],
                ["Buffer teď", `${num(b.buffer_rows)} řádků${b.buffer_oldest_ts ? ` · nejstarší ${dt(b.buffer_oldest_ts)}` : ""}`],
                ["Buffer maximum (kdy koliv)", `${num(b.buffer_peak_rows)} řádků`],
              ]} />
            </Section>
          </div>

          <Section title={`📥 Evidence bufferování — ${es.n || 0} epizod${d.sync_since ? ` (evidence od ${dt(d.sync_since)})` : " (evidence začíná touto verzí)"}`}>
            <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
              Epizoda = box po výpadku spojení dohrává data z lokálního bufferu (dávka se vzorky staršími než 3 min).
              „Výpadek" je doba od nejstaršího dohraného vzorku do první dávky po obnově; „dohrání" je doba, než se buffer vyprázdnil.
              Celkem dohráno z bufferu: <b>{num(es.rows_accepted)}</b> řádků, součet výpadků <b>{dur(es.offline_s)}</b>.
              {openEp && <span style={{ color: "var(--amber)" }}> ⏳ Právě se dohrává (od {dt(openEp.detected_at)}).</span>}
            </p>
            {(d.episodes || []).length ? (
              <table style={{ fontSize: 12 }}>
                <thead><tr><th>Výpadek od</th><th>Obnova spojení</th><th>Trvání výpadku</th><th>Dohráno</th><th>Dohrání trvalo</th><th>Řádků z bufferu</th><th>Duplicit</th><th>Dávek</th><th>Vrchol bufferu</th></tr></thead>
                <tbody>{d.episodes.map((e) => (
                  <tr key={e.id}>
                    <td>{dt(e.data_from)}</td>
                    <td>{dt(e.detected_at)}</td>
                    <td><b>{dur(secs(e.data_from, e.detected_at))}</b></td>
                    <td>{e.ended_at ? dt(e.ended_at) : <span style={{ color: "var(--amber)" }}>⏳ probíhá</span>}</td>
                    <td>{e.ended_at ? dur(secs(e.detected_at, e.ended_at)) : "—"}</td>
                    <td><b>{num(e.rows_accepted)}</b></td>
                    <td className="muted">{num(e.rows_dup)}</td>
                    <td className="muted">{num(e.batches)}</td>
                    <td className="muted">{num(e.peak_buffer_rows)}</td>
                  </tr>))}
                </tbody></table>
            ) : <p className="muted" style={{ fontSize: 12 }}>Zatím žádná epizoda bufferování nebyla zaznamenána.</p>}
          </Section>

          <Section title="📊 Statistika syncu (dávky telemetrie box → teraems)">
            <table style={{ fontSize: 12 }}>
              <thead><tr><th>Období</th><th>Dávek</th><th>Řádků</th><th>Přijato</th><th>Duplicit</th><th>Z bufferu (dávek)</th><th>Z bufferu (řádků)</th><th>Max. zpoždění dat</th></tr></thead>
              <tbody>{["24h", "7d", "30d", "90d"].map((k) => { const r = st[k] || {}; return (
                <tr key={k}><td><b>{k}</b></td><td>{num(r.batches)}</td><td>{num(r.rows_total)}</td><td>{num(r.rows_accepted)}</td>
                  <td className="muted">{num(r.rows_dup)}</td><td>{num(r.backfill_batches)}</td><td><b>{num(r.backfill_rows)}</b></td><td>{dur(r.max_lag_s)}</td></tr>); })}
              </tbody></table>
            <p className="muted" style={{ fontSize: 11.5, marginBottom: 0 }}>
              „Z bufferu" = dávky s daty staršími než 3 min (dohrávání po výpadku). Duplicity = řádky, které server už měl (opakovaná dávka po přerušeném potvrzení) — nic se neztrácí ani nezdvojuje.
            </p>
          </Section>

          <Section title={`🔌 Zařízení na boxu (${(d.modules || []).length})`}>
            {(d.modules || []).length ? (
              <table style={{ fontSize: 12 }}>
                <thead><tr><th>ID</th><th>Název</th><th>Adaptér</th><th>Typ</th><th>Transport</th><th>Poslední čtení</th><th>Stav</th></tr></thead>
                <tbody>{d.modules.map((m) => {
                  const hd = (b.heartbeat_devices || []).find((x) => x.device_uid === m.id) || {};
                  const tp = m.transport_params || {};
                  return (<tr key={m.id}>
                    <td style={{ fontFamily: "monospace", fontSize: 11 }}>{m.id}</td><td>{m.name}</td><td>{m.adapter}</td><td>{m.device_type || "—"}</td>
                    <td className="muted">{tp.host ? `TCP ${tp.host}:${tp.port || 502}` : tp.port ? `${tp.port}${tp.baudrate ? " @ " + tp.baudrate : ""}` : "—"}</td>
                    <td>{hd.last_read_ts ? `${dt(hd.last_read_ts)} (${ago(hd.last_read_ts)})` : "—"}</td>
                    <td>{hd.ok === true ? <span style={{ color: "var(--green)" }}>✅ čte</span> : hd.ok === false ? <span style={{ color: "#f85149" }} title={hd.error || ""}>❌ {hd.error || "chyba"}</span> : "—"}</td>
                  </tr>); })}
                </tbody></table>
            ) : <p className="muted" style={{ fontSize: 12 }}>Žádné zařízení není tomuto boxu přiřazeno (Moduly → EMSBOX).</p>}
          </Section>

          <Section title={`🔔 Alertové události (${(d.alerts || []).length})`}>
            {(d.alerts || []).length ? (
              <table style={{ fontSize: 12 }}>
                <thead><tr><th>Typ</th><th>Otevřeno</th><th>Uzavřeno</th><th>Trvání</th><th>Detail</th></tr></thead>
                <tbody>{d.alerts.map((a) => (
                  <tr key={a.id}><td>{ALERT_CZ[a.kind] || a.kind}</td><td>{dt(a.opened_at)}</td>
                    <td>{a.closed_at ? dt(a.closed_at) : <span style={{ color: "#f85149" }}>otevřeno</span>}</td>
                    <td>{dur(secs(a.opened_at, a.closed_at || new Date().toISOString()))}</td>
                    <td className="muted">{a.detail && typeof a.detail === "object"
                      ? Object.entries(a.detail).map(([k, v]) => `${k}: ${v}`).join(" · ") : a.detail || ""}</td></tr>))}
                </tbody></table>
            ) : <p className="muted" style={{ fontSize: 12 }}>Žádné alertové události (nebo pro box není alertové pravidlo — Lokality → alerty).</p>}
          </Section>

          {d.actions && (
            <Section title={`🛠 Servisní akce (${d.actions.length})`}>
              {d.actions.length ? (
                <table style={{ fontSize: 12 }}>
                  <thead><tr><th>Kdy</th><th>Akce</th><th>Zadal</th><th>Stav</th><th>Detail</th></tr></thead>
                  <tbody>{d.actions.map((h) => (
                    <tr key={h.id}><td>{dt(h.created_at)}</td><td>{ACTION_CZ_DYN(h.action)}</td><td>{h.username || "—"}</td>
                      <td>{{ pending: "⏳", delivered: "📨", done: "✅", failed: "❌" }[h.status] || h.status}</td>
                      <td className="muted">{h.detail || ""}</td></tr>))}
                  </tbody></table>
              ) : <p className="muted" style={{ fontSize: 12 }}>Žádné servisní akce.</p>}
            </Section>)}

          {raw && (
            <Section title="Surový poslední heartbeat (vše, co box poslal)">
              <pre style={{ fontSize: 11, whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(hb, null, 2)}</pre>
            </Section>)}
        </>)}
      </div>
    </div>
  );
}

function DetailBtn({ box }) {
  const [open, setOpen] = useState(false);
  return (<>
    <button className="btn" title="Detail boxu — vše, co o něm víme, vč. evidence bufferování"
            style={{ padding: "3px 8px", fontSize: 12, marginRight: 6 }} onClick={() => setOpen(true)}>🔎 detail</button>
    {open && <BoxDetail box={box} onClose={() => setOpen(false)} />}
  </>);
}

export default function Emsboxes() {
  const { vis } = useAuth();
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
              <th>Veřejná IP</th><th>Privátní IP</th><th>Síť</th><th>Disk</th><th>RAM</th><th>Buffer</th><th>Drift</th><th>Verze</th><th></th></tr></thead>
            <tbody>
              {d.boxes.map((b) => (
                <React.Fragment key={b.id}>
                <tr style={rowStyle(b.disk_free_mb)} title={lowDisk(b.disk_free_mb) ? "⚠ méně než 10 GB volného místa" : undefined}>
                  <td>{b.status === "online" ? "🟢" : b.status === "pairing" ? "🟡" : "🔴"}</td>
                  <td><b>{b.name}</b> <span className="muted">#{b.id}</span></td>
                  <td>{b.hostname || "—"}</td>
                  <td>{b.locality_name || b.locality_id}</td>
                  <td>{ago(b.last_heartbeat)}</td>
                  <td>{ago(b.last_ingest)}</td>
                  <td>{b.public_ip || "—"}</td>
                  <td>{b.private_ip ? <a href={`http://${b.private_ip}`} target="_blank" rel="noreferrer">{b.private_ip}</a> : "—"}</td>
                  <td>{b.wifi_ssid ? `📶 ${b.wifi_ssid}` : "🔌 LAN"}
                      {vis("box:psk") && b.wifi_psk && <Psk value={b.wifi_psk} />}</td>
                  <td style={lowDisk(b.disk_free_mb) ? { color: "#f85149", fontWeight: 700 } : {}}>{diskCell(b.disk_total_mb, b.disk_free_mb)}</td>
                  <td>{b.mem_total_mb != null ? `${gb(b.mem_used_mb)} / ${gb(b.mem_total_mb)}` : "—"}</td>
                  <td>{b.buffer_rows ?? "—"} ř.</td>
                  <td style={Math.abs(b.clock_drift_s || 0) > 60 ? { color: "#f85149" } : {}}>{b.clock_drift_s != null ? `${Math.round(b.clock_drift_s)} s` : "—"}</td>
                  <td>{b.agent_version || "—"} {vis("box:actions") && <UpdateBtn box={b} />}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{vis("box:detail") && <DetailBtn box={b} />}{vis("box:actions") && <><ConsoleBtn box={b} /><ResetUiPw box={b} /></>}</td>
                </tr>
                {b.last_action && <tr>
                  <td colSpan={99} style={{ paddingTop: 0, fontSize: 12 }}><ActionStatus box={b} /></td>
                </tr>}
                </React.Fragment>))}
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
