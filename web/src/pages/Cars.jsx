// 🚘 Auta — BMW CarData: připojení účtu (Device Code Flow), vozidla, mapování dat, živý stav.
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { CarCard } from "../components/CarCards";

const FLD = { padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };
const fmt = (iso) => (iso ? new Date(iso).toLocaleString("cs-CZ") : "—");

export default function Cars() {
  const { has } = useAuth();
  const [accs, setAccs] = useState([]);
  const [cars, setCars] = useState([]);
  const [locs, setLocs] = useState([]);
  const [mods, setMods] = useState([]);
  const [clientId, setClientId] = useState("");
  const [locId, setLocId] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [keysFor, setKeysFor] = useState(null);     // vin → surové deskriptory
  const [keys, setKeys] = useState({});
  const [roles, setRoles] = useState(null);
  const isAdmin = has("admin");
  const load = () => {
    if (isAdmin) api.carsAccounts().then(setAccs).catch(() => {});
    api.carsVehicles().then(setCars).catch(() => {});
  };
  useEffect(() => {
    load();
    if (isAdmin) { api.listLocalities().then((r) => setLocs(r || [])).catch(() => {}); api.listModules().then((r) => setMods((r || []).filter((m) => m.adapter === "goe_charger"))).catch(() => {}); }
    api.carsRoles().then(setRoles).catch(() => {});
    const t = setInterval(load, 10000); return () => clearInterval(t);
    /* eslint-disable-next-line */ }, []);
  const addAcc = async () => {
    setBusy(true); setMsg("");
    try { await api.carsAccountCreate({ client_id: clientId.trim(), locality_id: locId === "" ? null : Number(locId) }); setClientId(""); load(); }
    catch (e) { setMsg(e.message); } setBusy(false);
  };
  const connect = async (a) => {
    setBusy(true); setMsg("");
    try { const r = await api.carsConnect(a.id); setMsg(`Otevři odkaz a potvrď kód ${r.user_code} (platí do ${fmt(r.expires_at)})`); load(); }
    catch (e) { setMsg(e.message); } setBusy(false);
  };
  const sync = async (a) => { setBusy(true); setMsg(""); try { await api.carsSync(a.id); setMsg("Vozidla načtena."); load(); } catch (e) { setMsg(e.message); } setBusy(false); };
  const del = async (a) => { if (!window.confirm("Odebrat účet BMW CarData (a jeho vozidla) z TERA?")) return; await api.carsAccountDelete(a.id); load(); };
  const patchCar = async (vin, p) => { try { await api.carsVehiclePatch(vin, p); load(); } catch (e) { setMsg(e.message); } };
  const showKeys = async (vin) => { setKeysFor(vin); setKeys(await api.carsVehicleState(vin).catch(() => ({}))); };

  return (
    <main>
      <h1 style={{ fontSize: 20, marginTop: 0 }}>🚘 Auta — BMW CarData</h1>
      <p className="muted" style={{ fontSize: 12.5, marginTop: -6 }}>
        Oficiální zákaznické API BMW (EU Data Act): živý stream (MQTT) + REST (50 dotazů/den). Jen čtení — do auta se nic nezapisuje.
        Client ID vytvoříš v My BMW (web): Přehled vozidel → vůz → BMW CarData → Technický přístup → Vytvořit klienta; zapni oba přepínače (API + Stream).
      </p>

      {isAdmin && (
        <div className="panel" style={{ marginBottom: 14 }}>
          <b style={{ fontSize: 14 }}>Účty BMW</b>
          {accs.map((a) => (
            <div key={a.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 10, margin: "8px 0", fontSize: 13 }}>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
                <b>#{a.id}</b><code style={{ fontSize: 12 }}>{a.client_id}</code>
                <span>stav: <b style={{ color: a.status === "connected" ? "var(--green)" : a.status === "pending" ? "var(--amber)" : "#f85149" }}>{{ new: "nepřipojeno", pending: "čeká na potvrzení", connected: "připojeno", expired: "vypršelo", error: "chyba" }[a.status] || a.status}</b></span>
                {a.locality_id && <span className="muted">lokalita {a.locality_id}</span>}
                {a.status === "connected" && <>
                  <span>stream: <b>{a.stream_status || "—"}</b>{a.stream_msgs ? ` · ${a.stream_msgs} zpráv` : ""}</span>
                  <span className="muted">REST dnes {a.rest_calls_today || 0}/50 · refresh do {fmt(a.refresh_expires_at)}</span></>}
              </div>
              {a.status === "pending" && a.user_code && (
                <div style={{ marginTop: 6, padding: 8, border: "1px dashed var(--amber)", borderRadius: 8 }}>
                  1. Otevři <a href={a.verification_uri} target="_blank" rel="noreferrer">{a.verification_uri}</a> · 2. přihlas se BMW ID · 3. potvrď kód <b style={{ fontSize: 16 }}>{a.user_code}</b>
                  <div className="muted" style={{ fontSize: 12 }}>TERA se každých pár sekund ptá, jestli už je potvrzeno (do {fmt(a.device_expires_at)}).</div>
                </div>)}
              {a.last_error && <div style={{ color: "#f85149", fontSize: 12, marginTop: 4 }}>{a.last_error}</div>}
              <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                {a.status !== "connected" && <button className="btn primary" disabled={busy} onClick={() => connect(a)}>🔑 Připojit (Device Code)</button>}
                {a.status === "connected" && <button className="btn" disabled={busy} onClick={() => sync(a)}>🔄 Načíst vozidla</button>}
                {a.status === "connected" && <button className="btn" disabled={busy} onClick={() => connect(a)} title="nová autorizace (např. po vypršení refresh tokenu po 14 dnech)">🔑 Znovu autorizovat</button>}
                <button className="btn" disabled={busy} onClick={() => del(a)}>✕ odebrat</button>
              </div>
            </div>))}
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
            <input style={{ ...FLD, width: 330 }} placeholder="Client ID z My BMW (xxxxxxxx-xxxx-…)" value={clientId} onChange={(e) => setClientId(e.target.value)} />
            <select style={FLD} value={locId} onChange={(e) => setLocId(e.target.value)}>
              <option value="">— lokalita —</option>{locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
            <button className="btn primary" disabled={busy || clientId.length < 30} onClick={addAcc}>+ přidat účet</button>
            {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
          </div>
        </div>)}

      <div className="panel">
        <b style={{ fontSize: 14 }}>Vozidla</b>
        {!cars.length && <p className="muted" style={{ fontSize: 12.5 }}>Zatím žádné — po připojení účtu klikni „Načíst vozidla“ (nebo počkej na první zprávu ze streamu).</p>}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 10, marginTop: 8 }}>
          {cars.map((c) => <CarCard key={c.vin} car={c} />)}
        </div>
        {isAdmin && cars.length > 0 && (
          <table style={{ fontSize: 12, marginTop: 12, width: "100%" }}>
            <thead><tr><th>VIN</th><th>Název</th><th>Lokalita</th><th>Wallbox</th><th>Kapacita kWh</th><th>Data</th></tr></thead>
            <tbody>{cars.map((c) => (
              <tr key={c.vin}>
                <td><code>{c.vin}</code></td>
                <td><input style={{ ...FLD, width: 120 }} defaultValue={c.name || ""} onBlur={(e) => e.target.value !== (c.name || "") && patchCar(c.vin, { name: e.target.value })} /></td>
                <td><select style={FLD} value={c.locality_id ?? ""} onChange={(e) => patchCar(c.vin, { locality_id: e.target.value === "" ? null : Number(e.target.value) })}>
                  <option value="">—</option>{locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></td>
                <td><select style={FLD} value={c.wallbox_module_id ?? ""} onChange={(e) => patchCar(c.vin, { wallbox_module_id: e.target.value || null })}>
                  <option value="">—</option>{mods.map((m) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)}</select></td>
                <td><input style={{ ...FLD, width: 70 }} defaultValue={c.capacity_kwh ?? ""} placeholder="auto" onBlur={(e) => patchCar(c.vin, { capacity_kwh: e.target.value === "" ? null : Number(e.target.value) })} /></td>
                <td><button className="btn" style={{ padding: "2px 8px" }} onClick={() => showKeys(c.vin)}>🔎 přijaté klíče ({c.keys_received})</button></td>
              </tr>))}
            </tbody></table>)}
      </div>

      {roles?.stream_keys?.length > 0 && <StreamKeys keys={roles.stream_keys} />}

      {keysFor && roles && (
        <div onClick={() => setKeysFor(null)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.6)", zIndex: 95, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div onClick={(e) => e.stopPropagation()} className="panel" style={{ width: "min(900px, 96vw)", maxHeight: "90vh", overflow: "auto", padding: 14 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}><b>🔎 Přijaté deskriptory — {keysFor}</b>
              <button className="btn" style={{ marginLeft: "auto", padding: "3px 10px" }} onClick={() => setKeysFor(null)}>✕</button></div>
            <KeyMapEditor vin={keysFor} car={cars.find((c) => c.vin === keysFor)} roles={roles} keys={keys} onSave={(km) => patchCar(keysFor, { key_map: km })} />
            <table style={{ fontSize: 11.5, marginTop: 10, width: "100%" }}>
              <thead><tr><th>Klíč (TDC)</th><th>Hodnota</th><th>Jednotka</th><th>Čas</th><th>Zdroj</th></tr></thead>
              <tbody>{Object.entries(keys).map(([k, v]) => (
                <tr key={k}><td><code>{k}</code></td><td><b>{String(v.value)}</b></td><td className="muted">{v.unit || ""}</td><td className="muted">{fmt(v.ts)}</td><td className="muted">{v.source}</td></tr>))}
                {!Object.keys(keys).length && <tr><td colSpan={5} className="muted">Zatím nic — stream posílá hodnoty, až se v autě změní; REST čtení běží 1× za 40 min.</td></tr>}
              </tbody></table>
          </div>
        </div>)}
    </main>
  );
}

function StreamKeys({ keys }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const txt = keys.map((k) => k.key).join("\n");
  const copy = async () => { try { await navigator.clipboard.writeText(txt); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* bez clipboardu */ } };
  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }} onClick={() => setOpen(!open)}>
        <b style={{ fontSize: 14 }}>📡 Klíče pro CarData Stream ({keys.length})</b>
        <span className="muted" style={{ fontSize: 12 }}>co zaškrtnout v My BMW → BMW CarData → Datový stream</span>
        <span style={{ marginLeft: "auto" }}>{open ? "▴" : "▾"}</span>
      </div>
      {open && (
        <div style={{ marginTop: 8, fontSize: 12.5 }}>
          <p className="muted" style={{ margin: "0 0 8px" }}>
            Stream posílá jen klíče zaškrtnuté v portálu; neposílá nic, dokud se hodnota v autě nezmění. Tohle je minimum, se kterým TERA pracuje
            (dashboard, kWh do cíle, plánovač nabíjení). Katalog se liší podle modelu — klíč, který auto nemá, zůstane prázdný a nic nerozbije.
          </p>
          <table style={{ width: "100%", fontSize: 12 }}>
            <tbody>{keys.map((k, i) => (
              <tr key={k.key}><td className="muted" style={{ width: 24 }}>{i + 1}.</td><td><code style={{ fontSize: 11.5 }}>{k.key}</code></td><td className="muted">{k.why}</td></tr>))}
            </tbody></table>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <button className="btn" onClick={copy}>{copied ? "✅ zkopírováno" : "📋 kopírovat seznam"}</button>
            <span className="muted" style={{ fontSize: 11.5 }}>Stejný seznam si TERA vyžádá i pro REST kontejner (doplňkové čtení à 40 min).</span>
          </div>
        </div>)}
    </div>
  );
}

function KeyMapEditor({ car, roles, keys, onSave }) {
  const [km, setKm] = useState({ ...roles.default_key_map, ...(car?.key_map || {}) });
  const opts = Object.keys(keys);
  const LBL = roles.role_labels || {};
  return (
    <div style={{ fontSize: 12.5, marginTop: 8 }}>
      <div className="muted" style={{ marginBottom: 4 }}>Mapování rolí → deskriptor (katalog se liší podle modelu; vyber z toho, co auto opravdu posílá):</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 4 }}>
        {roles.roles.map((r) => (
          <label key={r} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ width: 150 }}>{LBL[r] || r}</span>
            <input list={`k-${r}`} style={{ ...FLD, flex: 1, fontSize: 11.5 }} value={km[r] || ""} onChange={(e) => setKm({ ...km, [r]: e.target.value })} />
            <datalist id={`k-${r}`}>{opts.map((o) => <option key={o} value={o} />)}</datalist>
            <span style={{ width: 16 }}>{keys[km[r]] ? "✅" : "—"}</span>
          </label>))}
      </div>
      <button className="btn primary" style={{ marginTop: 6 }} onClick={() => onSave(km)}>Uložit mapování</button>
    </div>
  );
}
