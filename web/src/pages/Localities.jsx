import { useEffect, useState } from "react";
import { api } from "../api";

const emptyLoc = { name: "", address: "", region: "CZ", note: "" };

const fmtDT = (iso) => {
  const d = new Date(iso);
  return d.toLocaleString("cs-CZ", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
};

function OutageSection({ loc, onChange }) {
  const [form, setForm] = useState({
    cez_ean: loc.cez_ean || "", cez_meter: loc.cez_meter || "",
    addr_zip: loc.addr_zip || "", addr_city: loc.addr_city || "", addr_street: loc.addr_street || "",
  });
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const loadOut = () => api.localityOutages(loc.id).then(setData).catch(() => {});
  useEffect(() => { loadOut(); }, [loc.id]);

  const set = (k, v) => setForm({ ...form, [k]: v });
  const save = async () => {
    setBusy(true); setMsg("");
    try { await api.updateLocality(loc.id, form); onChange(); setMsg("Uloženo."); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };
  const refresh = async () => {
    setBusy(true); setMsg("");
    try { const r = await api.refreshOutages(loc.id); setData({ ...data, ...r }); setMsg(`Načteno z ČEZ: ${r.fetched} odstávek.`); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const by = loc.outage_by;
  const outages = data?.outages || [];

  return (
    <div style={{ marginTop: 16, borderTop: "1px solid var(--border, #2a2a35)", paddingTop: 12 }}>
      <label className="muted" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}>
        Plánované odstávky (ČEZ)
      </label>
      <p className="muted" style={{ fontSize: 12, margin: "4px 0 10px" }}>
        Dotaz použije první vyplněnou možnost v pořadí: EAN → číslo elektroměru → adresa.
        {by ? <> Aktuálně se ptá podle: <strong>{by}</strong>.</> : <> Zatím není vyplněn žádný identifikátor.</>}
      </p>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div className="field" style={{ marginBottom: 0, minWidth: 200 }}><label>EAN (18 míst)</label>
          <input value={form.cez_ean} onChange={(e) => set("cez_ean", e.target.value)} placeholder="859182400…" /></div>
        <div className="field" style={{ marginBottom: 0, minWidth: 150 }}><label>Číslo elektroměru</label>
          <input value={form.cez_meter} onChange={(e) => set("cez_meter", e.target.value)} /></div>
      </div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginTop: 8 }}>
        <div className="field" style={{ marginBottom: 0, maxWidth: 110 }}><label>PSČ</label>
          <input value={form.addr_zip} onChange={(e) => set("addr_zip", e.target.value)} placeholder="742 21" /></div>
        <div className="field" style={{ marginBottom: 0, minWidth: 160 }}><label>Město / obec</label>
          <input value={form.addr_city} onChange={(e) => set("addr_city", e.target.value)} /></div>
        <div className="field" style={{ marginBottom: 0, minWidth: 160 }}><label>Ulice</label>
          <input value={form.addr_street} onChange={(e) => set("addr_street", e.target.value)} /></div>
        <button className="btn primary" onClick={save} disabled={busy}>Uložit</button>
        <button className="btn" onClick={refresh} disabled={busy || !by} title={by ? "" : "Vyplň a ulož identifikátor"}>Načíst teď</button>
      </div>
      {msg && <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>{msg}</p>}

      <div style={{ marginTop: 10 }}>
        {outages.length === 0 && <span className="muted" style={{ fontSize: 13 }}>Žádné nadcházející plánované odstávky.</span>}
        {outages.map((o) => (
          <div key={o.uid} style={{ fontSize: 13, padding: "6px 0", borderBottom: "1px solid var(--border, #23232b)" }}>
            <strong>{fmtDT(o.start)} – {fmtDT(o.end)}</strong>
            {o.number && <span className="muted"> · č. {o.number}</span>}
            {o.locations && <div className="muted" style={{ fontSize: 12 }}>{o.locations}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function ForecastSection({ loc, onChange }) {
  const [lat, setLat] = useState(loc.lat ?? "");
  const [lon, setLon] = useState(loc.lon ?? "");
  const [kwp, setKwp] = useState(loc.pv_kwp_total ?? "");
  const [blocks, setBlocks] = useState([]);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.forecastBlocks(loc.id).then((r) => setBlocks(r.blocks.length ? r.blocks
      : [{ name: "Blok 1", share_pct: 100, panel_type: "normal", tilt: 30, azimuth: 0, pr: 0.8, enabled: true }]))
      .catch(() => {});
  }, [loc.id]);

  const search = async () => {
    if (q.length < 2) return;
    try { setHits((await api.geocode(q)).results); } catch { setHits([]); }
  };
  const pick = (h) => { setLat(h.lat); setLon(h.lon); setHits([]); setQ(h.label); };

  const setBlk = (i, k, v) => setBlocks(blocks.map((b, j) => j === i ? { ...b, [k]: v } : b));
  const addBlk = () => setBlocks([...blocks, { name: `Blok ${blocks.length + 1}`, share_pct: 0, panel_type: "normal", tilt: 30, azimuth: 0, pr: 0.8, enabled: true }]);
  const delBlk = (i) => setBlocks(blocks.filter((_, j) => j !== i));
  const shareSum = blocks.reduce((s, b) => s + Number(b.share_pct || 0), 0);
  const kwpMissing = kwp === "" || isNaN(Number(kwp)) || Number(kwp) <= 0;

  const save = async () => {
    setBusy(true); setMsg("");
    try {
      await api.updateLocality(loc.id, {
        lat: lat === "" ? null : Number(lat), lon: lon === "" ? null : Number(lon),
        pv_kwp_total: kwp === "" ? null : Number(kwp),
      });
      await api.setForecastBlocks(loc.id, blocks.map((b) => ({
        name: b.name, share_pct: Number(b.share_pct || 0), panel_type: b.panel_type,
        tilt: Number(b.tilt || 0), azimuth: Number(b.azimuth || 0), pr: Number(b.pr || 0.8), enabled: b.enabled !== false,
      })));
      onChange(); setMsg("Uloženo.");
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };
  const recompute = async () => {
    setBusy(true); setMsg("");
    try { const r = await api.refreshForecast(loc.id); setMsg(`Přepočítáno: ${r.points} bodů.`); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const inp = { width: "100%", padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };
  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>☀️ Predikce výroby — umístění a panely</div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 6 }}>
        <div style={{ flex: "2 1 220px", position: "relative" }}>
          <label style={{ fontSize: 12 }}>Město (fulltext → poloha)</label>
          <div style={{ display: "flex", gap: 6 }}>
            <input style={inp} value={q} onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && search()} placeholder="např. Kopřivnice" />
            <button onClick={search} disabled={busy}>Najít</button>
          </div>
          {hits.length > 0 && (
            <div style={{ position: "absolute", zIndex: 5, background: "var(--card,#161b22)", border: "1px solid var(--border)", borderRadius: 6, marginTop: 2, width: "100%", maxHeight: 180, overflow: "auto" }}>
              {hits.map((h, i) => (
                <div key={i} onClick={() => pick(h)} style={{ padding: "6px 8px", cursor: "pointer", fontSize: 13 }}>
                  {h.label} <span className="muted">({h.lat?.toFixed(3)}, {h.lon?.toFixed(3)})</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ flex: "1 1 90px" }}><label style={{ fontSize: 12 }}>Lat</label><input style={inp} value={lat} onChange={(e) => setLat(e.target.value)} /></div>
        <div style={{ flex: "1 1 90px" }}><label style={{ fontSize: 12 }}>Lon</label><input style={inp} value={lon} onChange={(e) => setLon(e.target.value)} /></div>
        <div style={{ flex: "1 1 90px" }}><label style={{ fontSize: 12 }}>FVE kWp celkem</label><input style={{ ...inp, borderColor: kwpMissing ? "#e5534b" : "var(--border)" }} value={kwp} onChange={(e) => setKwp(e.target.value)} placeholder="např. 23" /></div>
      </div>

      <div style={{ fontSize: 12, fontWeight: 600, margin: "6px 0 2px" }}>
        Bloky panelů <span className="muted" style={{ fontWeight: 400 }}>(součet podílů {shareSum} %{shareSum !== 100 ? " — mělo by být 100" : ""})</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
          <thead><tr style={{ textAlign: "left", opacity: 0.7 }}>
            <th>Název</th><th>Typ</th><th>Podíl %</th><th>Směr °</th><th>Sklon °</th><th>PR</th><th></th>
          </tr></thead>
          <tbody>
            {blocks.map((b, i) => (
              <tr key={i}>
                <td><input style={inp} value={b.name} onChange={(e) => setBlk(i, "name", e.target.value)} /></td>
                <td>
                  <select value={b.panel_type} onChange={(e) => setBlk(i, "panel_type", e.target.value)}>
                    <option value="normal">normální</option>
                    <option value="bifacial">bifaciální</option>
                  </select>
                </td>
                <td><input style={{ ...inp, width: 60 }} value={b.share_pct} onChange={(e) => setBlk(i, "share_pct", e.target.value)} /></td>
                <td><input style={{ ...inp, width: 60 }} value={b.azimuth} onChange={(e) => setBlk(i, "azimuth", e.target.value)} /></td>
                <td><input style={{ ...inp, width: 60 }} value={b.tilt} onChange={(e) => setBlk(i, "tilt", e.target.value)} /></td>
                <td><input style={{ ...inp, width: 60 }} value={b.pr} onChange={(e) => setBlk(i, "pr", e.target.value)} /></td>
                <td><button onClick={() => delBlk(i)} title="Odebrat">✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 11, margin: "4px 0" }}>
        Směr: 0 = jih, −90 = východ, +90 = západ, ±180 = sever. Sklon: 0 = naplocho, 90 = svisle (plot). PR se časem sám doladí proti reálné výrobě.
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button onClick={addBlk} disabled={busy}>+ blok</button>
        <button onClick={save} disabled={busy || kwpMissing} style={{ fontWeight: 600 }}>Uložit</button>
        <button onClick={recompute} disabled={busy}>Přepočítat predikci</button>
        {kwpMissing && <span style={{ fontSize: 12, color: "#e5534b" }}>Vyplň „FVE kWp celkem".</span>}
        {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
      </div>
    </div>
  );
}

function TariffSection({ loc }) {
  const blank = {
    mode: "spot", valid_from: new Date().toISOString().slice(0, 10), monthly_fee: 0,
    two_tariff: false, nt_hours: "", spot_buy_surcharge: 0, spot_sell_fee: 200,
    dist_buy_vt: 0, dist_buy_nt: 0, levies: 0, fix_buy_vt: 0, fix_buy_nt: 0, fix_sell: 0,
    fx_source: "cnb", fx_eur_czk: null,
  };
  const [t, setT] = useState(blank);
  const [versions, setVersions] = useState([]);
  const [fx, setFx] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const reload = () => api.getTariff(loc.id).then((r) => {
    setVersions(r.versions || []); setFx(r.fx || null);
    if (r.effective) setT({ ...blank, ...r.effective, valid_from: blank.valid_from });
  }).catch(() => {});
  useEffect(() => { reload(); }, [loc.id]);

  const set = (k, v) => setT({ ...t, [k]: v });
  const save = async () => {
    setBusy(true); setMsg("");
    try { await api.addTariff(loc.id, t); setMsg("Uložena nová verze."); reload(); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };
  const del = async (vid) => { await api.deleteTariff(vid).catch(() => {}); reload(); };

  const inp = { width: "100%", padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };
  const Num = ({ k, label, suf }) => (
    <div style={{ flex: "1 1 120px" }}>
      <label style={{ fontSize: 12 }}>{label}{suf ? <span className="muted"> {suf}</span> : null}</label>
      <input style={inp} value={t[k] ?? 0} onChange={(e) => set(k, e.target.value === "" ? 0 : Number(e.target.value))} />
    </div>
  );

  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
        💰 Cena a tarif {fx && <span className="muted" style={{ fontWeight: 400 }}>· kurz ČNB {fx.eur_czk?.toFixed(3)} Kč/€ ({fx.day})</span>}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 6 }}>
        <div style={{ flex: "1 1 130px" }}>
          <label style={{ fontSize: 12 }}>Režim</label>
          <select value={t.mode} onChange={(e) => set("mode", e.target.value)} style={{ width: "100%" }}>
            <option value="spot">spot (dle OTE + složky)</option>
            <option value="fixed">pevná cena (Kč/kWh)</option>
          </select>
        </div>
        <Num k="monthly_fee" label="Měsíční paušál" suf="Kč" />
        <div style={{ flex: "1 1 130px" }}>
          <label style={{ fontSize: 12 }}>Platí od</label>
          <input type="date" style={inp} value={t.valid_from} onChange={(e) => set("valid_from", e.target.value)} />
        </div>
        <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 5, flex: "1 1 120px" }}>
          <input type="checkbox" checked={!!t.two_tariff} onChange={(e) => set("two_tariff", e.target.checked)} /> dvoutarif (VT/NT)
        </label>
      </div>

      {t.two_tariff && (
        <div style={{ marginBottom: 6 }}>
          <label style={{ fontSize: 12 }}>Hodiny NT <span className="muted">(0–23, čárkou; pražský čas)</span></label>
          <input style={inp} value={t.nt_hours || ""} onChange={(e) => set("nt_hours", e.target.value)} placeholder="např. 0,1,2,3,4,22,23" />
        </div>
      )}

      {t.mode === "spot" ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
          <Num k="spot_buy_surcharge" label="Přirážka nákup" suf="Kč/MWh" />
          <Num k="spot_sell_fee" label="Provize prodej" suf="Kč/MWh" />
          <Num k="dist_buy_vt" label="Distribuce VT" suf="Kč/MWh" />
          {t.two_tariff && <Num k="dist_buy_nt" label="Distribuce NT" suf="Kč/MWh" />}
          <Num k="levies" label="Poplatky/daň" suf="Kč/MWh" />
        </div>
      ) : (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
          <Num k="fix_buy_vt" label={t.two_tariff ? "Nákup VT" : "Nákup"} suf="Kč/kWh" />
          {t.two_tariff && <Num k="fix_buy_nt" label="Nákup NT" suf="Kč/kWh" />}
          <Num k="fix_sell" label="Výkup" suf="Kč/kWh" />
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button onClick={save} disabled={busy} style={{ fontWeight: 600 }}>Uložit jako novou verzi</button>
        {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
      </div>

      {versions.length > 0 && (
        <div style={{ marginTop: 6, fontSize: 12 }}>
          <span className="muted">Verze: </span>
          {versions.map((v) => (
            <span key={v.id} style={{ marginRight: 8 }}>
              {v.valid_from} ({v.mode}){" "}
              <button onClick={() => del(v.id)} title="Smazat verzi" style={{ padding: "0 5px" }}>✕</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function LocalityCard({ loc, allUsers, allModules, onChange }) {
  const [uSel, setUSel] = useState("");
  const [dSel, setDSel] = useState("");

  const assignedU = new Set(loc.users.map((u) => u.id));
  const assignedD = new Set(loc.devices.map((d) => d.id));
  const freeUsers = allUsers.filter((u) => !assignedU.has(u.id));
  const freeMods = allModules.filter((m) => !assignedD.has(m.id));

  const addU = async () => { if (uSel) { await api.assignUser(loc.id, Number(uSel)); setUSel(""); onChange(); } };
  const rmU = async (uid) => { await api.unassignUser(loc.id, uid); onChange(); };
  const addD = async () => { if (dSel) { await api.assignDevice(loc.id, dSel); setDSel(""); onChange(); } };
  const rmD = async (mid) => { await api.unassignDevice(loc.id, mid); onChange(); };
  const rename = async () => {
    const name = prompt("Název lokality:", loc.name); if (name === null) return;
    const note = prompt("Poznámka:", loc.note || ""); if (note === null) return;
    await api.updateLocality(loc.id, { name, note }); onChange();
  };
  const del = async () => { if (confirm(`Smazat lokalitu „${loc.name}"? Zařízení se odpojí, uživatelské vazby se zruší.`)) { await api.deleteLocality(loc.id); onChange(); } };

  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <h3 style={{ margin: 0 }}>{loc.name}</h3>
        <span className="muted" style={{ fontSize: 13 }}>{[loc.address, loc.region].filter(Boolean).join(" · ")}</span>
        <div style={{ marginLeft: "auto" }}>
          <button className="btn" onClick={rename} style={{ marginRight: 8 }}>Upravit</button>
          <button className="btn danger" onClick={del}>Smazat</button>
        </div>
      </div>
      {loc.note && <p className="muted" style={{ fontSize: 13, marginTop: 6 }}>{loc.note}</p>}

      <div className="row" style={{ marginTop: 14, alignItems: "flex-start", gap: 30 }}>
        <div style={{ flex: 1 }}>
          <label className="muted" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}>Zařízení</label>
          <div style={{ margin: "6px 0" }}>
            {loc.devices.length === 0 && <span className="muted">žádné</span>}
            {loc.devices.map((d) => (
              <span key={d.id} className="role" style={{ marginRight: 6, marginBottom: 6, display: "inline-block" }}>
                {d.name || d.id} <button className="linkx" onClick={() => rmD(d.id)}>×</button>
              </span>
            ))}
          </div>
          <div className="row" style={{ gap: 6 }}>
            <select value={dSel} onChange={(e) => setDSel(e.target.value)}>
              <option value="">— přidat zařízení —</option>
              {freeMods.map((m) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)}
            </select>
            <button className="btn" onClick={addD} disabled={!dSel}>Přidat</button>
          </div>
        </div>

        <div style={{ flex: 1 }}>
          <label className="muted" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".05em" }}>Uživatelé</label>
          <div style={{ margin: "6px 0" }}>
            {loc.users.length === 0 && <span className="muted">žádní</span>}
            {loc.users.map((u) => (
              <span key={u.id} className="role" style={{ marginRight: 6, marginBottom: 6, display: "inline-block" }}>
                {u.full_name || u.username} <button className="linkx" onClick={() => rmU(u.id)}>×</button>
              </span>
            ))}
          </div>
          <div className="row" style={{ gap: 6 }}>
            <select value={uSel} onChange={(e) => setUSel(e.target.value)}>
              <option value="">— přidat uživatele —</option>
              {freeUsers.map((u) => <option key={u.id} value={u.id}>{u.full_name ? `${u.full_name} (${u.username})` : u.username}</option>)}
            </select>
            <button className="btn" onClick={addU} disabled={!uSel}>Přidat</button>
          </div>
        </div>
      </div>

      <OutageSection loc={loc} onChange={onChange} />
      <ForecastSection loc={loc} onChange={onChange} />
      <TariffSection loc={loc} />
    </div>
  );
}

export default function Localities() {
  const [locs, setLocs] = useState([]);
  const [users, setUsers] = useState([]);
  const [mods, setMods] = useState([]);
  const [nl, setNl] = useState(emptyLoc);
  const [err, setErr] = useState("");

  const load = () => api.listLocalities().then(setLocs).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.listUsers().then(setUsers).catch(() => {});
    api.listModules().then(setMods).catch(() => {});
  }, []);

  const create = async () => {
    setErr("");
    try { await api.createLocality({ ...nl, address: nl.address || null, note: nl.note || null }); setNl(emptyLoc); load(); }
    catch (e) { setErr(e.message); }
  };

  return (
    <main>
      <div className="panel" style={{ marginBottom: 20 }}>
        <h3>Nová lokalita</h3>
        <div className="row">
          <div className="field" style={{ marginBottom: 0 }}><label>Název</label>
            <input value={nl.name} onChange={(e) => setNl({ ...nl, name: e.target.value })} /></div>
          <div className="field" style={{ marginBottom: 0 }}><label>Adresa</label>
            <input value={nl.address} onChange={(e) => setNl({ ...nl, address: e.target.value })} /></div>
          <div className="field" style={{ marginBottom: 0, maxWidth: 90 }}><label>Region</label>
            <input value={nl.region} onChange={(e) => setNl({ ...nl, region: e.target.value })} /></div>
          <div className="field" style={{ marginBottom: 0 }}><label>Poznámka</label>
            <input value={nl.note} onChange={(e) => setNl({ ...nl, note: e.target.value })} /></div>
          <button className="btn primary" onClick={create} disabled={!nl.name.trim()}>Přidat lokalitu</button>
        </div>
        <p className="error">{err}</p>
      </div>

      {locs.length === 0 && <p className="muted">Zatím žádné lokality.</p>}
      {locs.map((l) => (
        <LocalityCard key={l.id} loc={l} allUsers={users} allModules={mods} onChange={load} />
      ))}
    </main>
  );
}
