import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

// Mezipaměť načtených řídicích registrů per modul (v rámci session SPA),
// ať se při každém otevření Řízení nečte znovu ze střídače.
const ctrlCache = {};

const norm = (s) => (s || "").toString().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

function SearchSelect({ value, options, onChange, placeholder = "— vyber —" }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const sel = options.find((o) => String(o.id) === String(value));
  const filtered = q ? options.filter((o) => norm(o.label).includes(norm(q))) : options;
  const item = { padding: "6px 10px", cursor: "pointer", fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };
  return (
    <div style={{ position: "relative" }}>
      <input value={open ? q : (sel ? sel.label : "")} placeholder={placeholder}
        onFocus={() => { setOpen(true); setQ(""); }} onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onBlur={() => setTimeout(() => setOpen(false), 150)} style={{ minWidth: 180 }} />
      {open && (
        <div style={{ position: "absolute", zIndex: 30, top: "100%", left: 0, right: 0, maxHeight: 240, overflowY: "auto",
          background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8, marginTop: 2, boxShadow: "0 8px 22px rgba(0,0,0,.45)" }}>
          {filtered.map((o) => (
            <div key={o.id} onMouseDown={() => { onChange(String(o.id)); setOpen(false); }}
              style={{ ...item, background: String(o.id) === String(value) ? "var(--panel-2)" : "transparent" }}>{o.label}</div>
          ))}
          {!filtered.length && <div style={{ ...item, color: "var(--muted)" }}>nic nenalezeno</div>}
        </div>
      )}
    </div>
  );
}

const emptyOut = {
  name: "", enabled: true, output_kind: "ewelink", target: "", trigger: "surplus",
  upper_soc: 100, lower_soc: 95, surplus_kw: 1.5, soc_min: 80, spot_max: "", min_on_min: 10,
  day_start: "", day_end: "", grid_guard_kw: "", grid_guard_min: "",
};

// stará hodnota (celá hodina) i "HH:MM" -> "HH:MM" pro <input type=time>
const hm = (v) => {
  if (v == null || v === "") return "";
  const s = String(v);
  if (s.includes(":")) { const [h, m] = s.split(":"); return `${String(+h).padStart(2, "0")}:${String(+(m || 0)).padStart(2, "0")}`; }
  if (/^\d+(\.\d+)?$/.test(s)) return `${String(Math.floor(+s)).padStart(2, "0")}:00`;
  return "";
};

function OutputsPanel({ locId }) {
  const [list, setList] = useState([]);
  const [gw, setGw] = useState([]);
  const [ew, setEw] = useState([]);
  const [f, setF] = useState(emptyOut);
  const [editing, setEditing] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(0);
  const [open, setOpen] = useState(false);

  const load = () => api.listOutputs().then((all) => setList(all.filter((o) => o.locality_id === locId))).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.controlModules().then(setGw).catch(() => {});
    api.ewelinkDevices().then((r) => setEw(r.devices || [])).catch(() => {});
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [locId]);

  const targets = f.output_kind === "ewelink"
    ? ew.map((d) => ({ id: d.deviceid, label: d.name || d.deviceid }))
    : gw.map((m) => ({ id: m.id, label: m.name || m.id }));

  const buildParams = () => f.trigger === "soc"
    ? { upper_soc: Number(f.upper_soc), lower_soc: Number(f.lower_soc),
        ...(f.day_start !== "" && f.day_end !== "" ? { day_start: f.day_start, day_end: f.day_end } : {}),
        ...(f.grid_guard_kw !== "" && f.grid_guard_min !== "" ? { grid_guard_kw: Number(f.grid_guard_kw), grid_guard_min: Number(f.grid_guard_min) } : {}) }
    : { surplus_kw: Number(f.surplus_kw), soc_min: Number(f.soc_min), min_on_min: Number(f.min_on_min),
        ...(f.spot_max !== "" && f.spot_max != null ? { spot_max: Number(f.spot_max) } : {}) };
  const body = () => ({ name: f.name.trim(), enabled: f.enabled, output_kind: f.output_kind, target: f.target,
    locality_id: locId, trigger: f.trigger, params: buildParams() });

  const reset = () => { setEditing(null); setF(emptyOut); };
  const save = async () => { setErr(""); try { if (editing) await api.updateOutput(editing, body()); else await api.createOutput(body()); reset(); setOpen(false); load(); } catch (e) { setErr(e.message); } };
  const edit = (o) => { setEditing(o.id); setOpen(true); setF({ name: o.name, enabled: o.enabled, output_kind: o.output_kind, target: o.target, trigger: o.trigger,
      upper_soc: o.params.upper_soc ?? 100, lower_soc: o.params.lower_soc ?? 95, surplus_kw: o.params.surplus_kw ?? 1.5,
      soc_min: o.params.soc_min ?? 80, spot_max: o.params.spot_max ?? "", min_on_min: o.params.min_on_min ?? 10,
      day_start: hm(o.params.day_start), day_end: hm(o.params.day_end),
      grid_guard_kw: o.params.grid_guard_kw ?? "", grid_guard_min: o.params.grid_guard_min ?? "" }); };
  const toggle = async (o) => { try { await api.updateOutput(o.id, { enabled: !o.enabled }); load(); } catch (e) { setErr(e.message); } };
  const remove = async (o) => { if (!confirm(`Smazat spotřebič „${o.name}"?`)) return; try { await api.deleteOutput(o.id); if (editing === o.id) reset(); load(); } catch (e) { setErr(e.message); } };
  const test = async (o, on) => { setBusy(o.id); setErr(""); try { await api.testOutput(o.id, on); setTimeout(load, 600); } catch (e) { setErr(e.message); } finally { setBusy(0); } };
  const unlock = async (o) => { try { await api.unlockOutput(o.id); load(); } catch (e) { setErr(e.message); } };

  const kindLabel = (k) => (k === "ewelink" ? "eWeLink" : "kontakt střídače");
  const trigLabel = (t) => (t === "soc" ? "SoC hystereze" : "přebytek/spot");
  const inp = { width: 120, padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 700, fontSize: 14 }}>🔌 Spínané spotřebiče</span>
        <span className="muted" style={{ fontSize: 12 }}>relé/spínače řízené podle SoC nebo přebytku FVE (bojler, spirála…)</span>
        <button className="btn" style={{ marginLeft: "auto", padding: "5px 12px" }} onClick={() => { reset(); setOpen(!open); }}>
          {open && !editing ? "Zavřít" : "+ Přidat spotřebič"}
        </button>
      </div>

      {open && (
        <div style={{ marginTop: 10, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          <div className="row" style={{ flexWrap: "wrap", alignItems: "flex-end", gap: 12 }}>
            <div><label style={{ fontSize: 12, display: "block" }}>Název</label><input value={f.name} placeholder="Ohřev vody" onChange={(e) => setF({ ...f, name: e.target.value })} style={inp} /></div>
            <div><label style={{ fontSize: 12, display: "block" }}>Cíl</label>
              <select value={f.output_kind} onChange={(e) => setF({ ...f, output_kind: e.target.value, target: "" })}>
                <option value="ewelink">eWeLink spínač</option><option value="goodwe_contact">Kontakt střídače</option>
              </select></div>
            <div><label style={{ fontSize: 12, display: "block" }}>Zařízení</label>
              <SearchSelect value={f.target} options={targets} onChange={(id) => setF({ ...f, target: id })} /></div>
            <div><label style={{ fontSize: 12, display: "block" }}>Spouštěč</label>
              <select value={f.trigger} onChange={(e) => setF({ ...f, trigger: e.target.value })}>
                <option value="surplus">Přebytek FVE / levný spot</option><option value="soc">SoC hystereze</option>
              </select></div>
          </div>
          <div className="row" style={{ flexWrap: "wrap", gap: 12, marginTop: 10 }}>
            {f.trigger === "soc" ? (
              <>
                <div><label style={{ fontSize: 12, display: "block" }}>Sepnout při SoC ≥ (%)</label><input value={f.upper_soc} onChange={(e) => setF({ ...f, upper_soc: e.target.value })} style={inp} /></div>
                <div><label style={{ fontSize: 12, display: "block" }}>Rozepnout při SoC ≤ (%)</label><input value={f.lower_soc} onChange={(e) => setF({ ...f, lower_soc: e.target.value })} style={inp} /></div>
                <div><label style={{ fontSize: 12, display: "block" }}>Jen přes den od–do (prázdné = nonstop)</label>
                  <span style={{ display: "inline-flex", gap: 4 }}>
                    <input type="time" value={f.day_start} onChange={(e) => setF({ ...f, day_start: e.target.value })} style={{ ...inp, width: 110 }} />
                    <input type="time" value={f.day_end} onChange={(e) => setF({ ...f, day_end: e.target.value })} style={{ ...inp, width: 110 }} />
                  </span>
                </div>
                <div><label style={{ fontSize: 12, display: "block" }}>Hlídač sítě – vypni, když import ze sítě &gt; (kW) déle než (min) <span className="muted">· prázdné = vypnuto</span></label>
                  <span style={{ display: "inline-flex", gap: 4 }}>
                    <input value={f.grid_guard_kw} placeholder="vyp" onChange={(e) => setF({ ...f, grid_guard_kw: e.target.value })} style={{ ...inp, width: 64 }} />
                    <input value={f.grid_guard_min} placeholder="vyp" onChange={(e) => setF({ ...f, grid_guard_min: e.target.value })} style={{ ...inp, width: 64 }} />
                  </span>
                </div>
              </>
            ) : (
              <>
                <div><label style={{ fontSize: 12, display: "block" }}>Přebytek ≥ (kW)</label><input value={f.surplus_kw} onChange={(e) => setF({ ...f, surplus_kw: e.target.value })} style={inp} /></div>
                <div><label style={{ fontSize: 12, display: "block" }}>A SoC ≥ (%)</label><input value={f.soc_min} onChange={(e) => setF({ ...f, soc_min: e.target.value })} style={{ ...inp, width: 90 }} /></div>
                <div><label style={{ fontSize: 12, display: "block" }}>Spot ≤ sepni i bez přebytku (Kč/MWh)</label><input value={f.spot_max} placeholder="např. 0" onChange={(e) => setF({ ...f, spot_max: e.target.value })} style={{ ...inp, width: 160 }} /></div>
                <div><label style={{ fontSize: 12, display: "block" }}>Min. doba sepnutí (min)</label><input value={f.min_on_min} onChange={(e) => setF({ ...f, min_on_min: e.target.value })} style={inp} /></div>
              </>
            )}
            <button className="btn primary" onClick={save} disabled={!f.name.trim() || !f.target}>{editing ? "Uložit změny" : "Přidat"}</button>
            {editing && <button className="btn" onClick={() => { reset(); setOpen(false); }}>Zrušit</button>}
          </div>
          <p className="muted" style={{ fontSize: 11.5, marginTop: 8 }}>
            {f.trigger === "surplus"
              ? "Sepne při přebytku FVE do sítě nad práh a baterii nabité aspoň na daný SoC; volitelně i při levném/záporném spotu pod limitem. Hystereze a min. doba brání cvakání."
              : "Sepne při horní mezi SoC, rozepne při dolní."}
          </p>
        </div>
      )}

      {list.length > 0 ? (
        <table style={{ marginTop: 10 }}>
          <thead><tr><th>Název</th><th>Cíl</th><th>Spouštěč</th><th>Stav</th><th>Aktivní</th><th>Test</th><th></th></tr></thead>
          <tbody>
            {list.map((o) => (
              <tr key={o.id}>
                <td>{o.name}</td>
                <td><span className="role">{kindLabel(o.output_kind)}</span><div className="muted" style={{ fontSize: 11, fontFamily: "var(--mono)" }}>{o.target}</div></td>
                <td className="muted">{trigLabel(o.trigger)}</td>
                <td><span className={o.is_on ? "badge-on" : "badge-off"}>{o.is_on ? "sepnuto" : "rozepnuto"}</span>
                  {o.off_lock_until && new Date(o.off_lock_until) > new Date() && (
                    <div style={{ fontSize: 11, marginTop: 3, color: "#d29922" }}>
                      🔒 uzamčeno hlídačem do {new Date(o.off_lock_until).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}
                      <button className="btn" onClick={() => unlock(o)} style={{ padding: "1px 7px", marginLeft: 6, fontSize: 11 }}>Odemknout</button>
                    </div>
                  )}
                </td>
                <td><span className={o.enabled ? "badge-on" : "badge-off"}>{o.enabled ? "ano" : "ne"}</span></td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="btn" disabled={busy === o.id} onClick={() => test(o, true)} style={{ padding: "2px 8px", marginRight: 4 }}>zap</button>
                  <button className="btn" disabled={busy === o.id} onClick={() => test(o, false)} style={{ padding: "2px 8px" }}>vyp</button>
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="btn" onClick={() => edit(o)} style={{ marginRight: 6 }}>Upravit</button>
                  <button className="btn" onClick={() => toggle(o)} style={{ marginRight: 6 }}>{o.enabled ? "Vypnout" : "Zapnout"}</button>
                  <button className="btn danger" onClick={() => remove(o)}>Smazat</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>Zatím žádný spínaný spotřebič.</p>}
      {err && <p className="error" style={{ marginTop: 8 }}>{err}</p>}
    </div>
  );
}

// Zařadí povel do fronty a počká na provedení kolektorem.
async function runCommand(moduleId, action, params, setStatus, label) {
  setStatus({ state: "pending", text: `Odesílám: ${label}…` });
  try {
    const { id: cmdId } = await api.enqueueCommand(moduleId, action, params);
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const c = await api.commandStatus(cmdId);
      if (c.status === "done") { setStatus({ state: "done", text: `✓ ${label} provedeno` }); return c.result; }
      if (c.status === "error") { setStatus({ state: "error", text: `✗ ${label}: ${c.result?.error || "chyba"}` }); return null; }
      setStatus({ state: "pending", text: `Čekám na kolektor (#${cmdId})…` });
    }
  } catch (e) { setStatus({ state: "error", text: `✗ ${e.message || e}` }); }
  return null;
}

function StatusLine({ status }) {
  if (!status) return null;
  const c = status.state === "error" ? "#e06c75" : status.state === "done" ? "var(--green)" : "var(--muted)";
  return <p style={{ marginTop: 8, fontSize: 13, color: c }}>{status.text}</p>;
}

function SpotDischargePanel({ moduleId }) {
  const [r, setR] = useState(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api.getSpotRule(moduleId).then(setR).catch(() => {}); }, [moduleId]);
  if (!r) return null;
  const set = (k, v) => setR({ ...r, [k]: v });
  const save = async () => {
    setMsg("Ukládám…");
    try {
      const saved = await api.setSpotRule(moduleId, {
        enabled: !!r.enabled, price_on: Number(r.price_on), price_off: Number(r.price_off),
        power_kw: Number(r.power_kw), soc_floor: Number(r.soc_floor),
      });
      setR(saved); setMsg("✓ Uloženo"); setTimeout(() => setMsg(""), 2500);
    } catch (e) { setMsg("✗ " + (e.message || e)); }
  };
  const fld = { width: 90, padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };
  const lbl = { fontSize: 12, display: "block", marginBottom: 2 };
  return (
    <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600, fontSize: 13.5, cursor: "pointer" }}>
        <input type="checkbox" checked={!!r.enabled} onChange={(e) => set("enabled", e.target.checked)} />
        🔻 Auto-vybíjení do sítě podle spotu
        {r.active && <span style={{ fontSize: 11, padding: "2px 8px", borderRadius: 999, background: "var(--amber)", color: "#0b0e13" }}>právě vybíjí</span>}
      </label>
      <p className="muted" style={{ fontSize: 11.5, margin: "4px 0 8px" }}>
        Když spot ≥ „zapnout", vybíjí zadaným výkonem do sítě. Vypne při spot &lt; „vypnout" nebo při dosažení podlahy SoC. Plánovač a ruční zásah mají přednost.
      </p>
      <div className="row" style={{ gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div><label style={lbl}>Zapnout při spotu ≥ (Kč/MWh)</label>
          <input value={r.price_on} onChange={(e) => set("price_on", e.target.value)} style={fld} /></div>
        <div><label style={lbl}>Vypnout při spotu &lt; (Kč/MWh)</label>
          <input value={r.price_off} onChange={(e) => set("price_off", e.target.value)} style={fld} /></div>
        <div><label style={lbl}>Výkon (kW)</label>
          <input value={r.power_kw} onChange={(e) => set("power_kw", e.target.value)} style={fld} /></div>
        <div><label style={lbl}>Podlaha SoC (%)</label>
          <input value={r.soc_floor} onChange={(e) => set("soc_floor", e.target.value)} style={fld} /></div>
        <button className="btn primary" onClick={save} style={{ padding: "6px 14px" }}>Uložit</button>
        {msg && <span className="muted" style={{ fontSize: 12 }}>{msg}</span>}
      </div>
    </div>
  );
}

function SolisControl({ mod }) {
  const has = (k) => (mod.control_enabled || []).includes(k);
  const [power, setPower] = useState(5);
  const [chA, setChA] = useState("");
  const [disA, setDisA] = useState("");
  const [socBackup, setSocBackup] = useState("");
  const [socForce, setSocForce] = useState("");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [curState, setCurState] = useState(null);

  const refreshState = () => api.controlStates(mod.id)
    .then((r) => setCurState((r.states || {})[mod.id] || null)).catch(() => {});
  useEffect(() => { refreshState(); const t = setInterval(refreshState, 10000); return () => clearInterval(t); /* eslint-disable-next-line */ }, [mod.id]);

  const ask = (msg) => window.confirm(msg);

  const force = async (action, label) => {
    if (!ask(`Opravdu poslat do měniče ${mod.id}: ${label}?`)) return;
    setBusy(true); await runCommand(mod.id, action, { power: Math.round(Number(power) * 100) }, setStatus, label); setBusy(false);
  };
  const stop = async () => {
    if (!ask(`Vrátit měnič ${mod.id} do normálu (Self-Use)?`)) return;
    setBusy(true); await runCommand(mod.id, "stop", {}, setStatus, "Stop (normál)"); setBusy(false);
  };
  const setLimit = async (action, params, label) => {
    if (!ask(`Opravdu nastavit ${label} na měniči ${mod.id}?`)) return;
    setBusy(true); await runCommand(mod.id, action, params, setStatus, label); setBusy(false);
  };
  const applyControls = (c) => {
    if (c["43012"] != null) setChA(c["43012"] / 10);
    if (c["43013"] != null) setDisA(c["43013"] / 10);
    if (c["43024"] != null) setSocBackup(c["43024"]);
    if (c["43030"] != null) setSocForce(c["43030"]);
  };
  const readNow = async () => {
    setBusy(true);
    const res = await runCommand(mod.id, "read_controls", {}, setStatus, "Načtení stavu");
    setBusy(false);
    const c = res?.controls;
    if (c) {
      applyControls(c);
      const at = new Date();
      ctrlCache[mod.id] = { c, at };
      setStatus({ state: "done", text: `✓ Načtení stavu provedeno ${at.toLocaleString("cs-CZ")}` });
    }
  };

  // Po otevření: použij mezipaměť (do 15 min), jinak čti z měniče. Ať se nečte při každém otevření.
  useEffect(() => {
    const hit = ctrlCache[mod.id];
    if (hit && Date.now() - hit.at.getTime() < 15 * 60 * 1000) {
      applyControls(hit.c);
      setStatus({ state: "done", text: `Z mezipaměti (z měniče načteno ${hit.at.toLocaleString("cs-CZ")})` });
    } else {
      readNow();
    }
    /* eslint-disable-line */
  }, [mod.id]);

  const fld = { width: 110, padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h3 style={{ marginBottom: 2, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {mod.id} <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· Solis</span>
        {(() => {
          const B = {
            idle: { t: "Self-Use", bg: "var(--blue)" },
            force_charge: { t: "⚡ Nabíjení", bg: "var(--green)" },
            force_discharge: { t: "🔻 Vybíjení do sítě", bg: "var(--amber)" },
            spiral: { t: "🌀 Spirála", bg: "#a371f7" },
          };
          const a = curState?.action || "idle";
          const b = B[a] || { t: a, bg: "var(--muted)" };
          const src = curState?.source === "planner" ? " · plánovač" : curState?.source === "spot" ? " · spot" : curState?.source === "manual" ? " · ručně" : "";
          return <span style={{ padding: "3px 12px", borderRadius: 999, fontSize: 12.5, fontWeight: 700,
            color: "#0b0e13", background: b.bg, whiteSpace: "nowrap" }}>{b.t}{src}</span>;
        })()}
      </h3>
      <p className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
        ⚠️ Reálně zapisuje do měniče. Výkon zadáváš v <b>kW pro celé úložiště</b> (obě baterie dohromady). Vybíjení jde do sítě jen nad rámec spotřeby domu. (nabíjení reg. 43136, vybíjení 43129; jednotka 10 W)
      </p>

      <div style={{ fontWeight: 600, fontSize: 13, margin: "8px 0 4px" }}>Ruční řízení</div>
      <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ fontSize: 12 }}>výkon <span className="muted">(kW, celé úložiště)</span> <input value={power} onChange={(e) => setPower(e.target.value)} style={{ ...fld, width: 80 }} /></label>
        {has("force_charge") && <button className="btn" disabled={busy} onClick={() => force("force_charge", `Nabíjet teď (${power} kW)`)}>⚡ Nabíjet teď</button>}
        {has("force_discharge") && <button className="btn" disabled={busy} onClick={() => force("force_discharge", `Vybíjet teď (${power} kW)`)}>🔻 Vybíjet teď</button>}
        <button className="btn" disabled={busy} style={{ color: "#e06c75" }} onClick={stop}>⏹ Stop</button>
      </div>

      <div style={{ fontWeight: 600, fontSize: 13, margin: "14px 0 6px", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span>Limity a režim</span>
        <button className="btn primary" style={{ padding: "8px 18px", fontSize: 14, fontWeight: 700 }} disabled={busy} onClick={readNow}>
          ⟳ Načíst aktuální z měniče
        </button>
        {busy && <span className="muted" style={{ fontSize: 12 }}>čtu z měniče…</span>}
        <span className="muted" style={{ fontSize: 11, fontWeight: 400 }}>(hodnoty jsou živé z měniče, ne z databáze)</span>
      </div>
      <div className="row" style={{ gap: 14, flexWrap: "wrap" }}>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Nabíjecí proud (A)</label>
          <input value={chA} onChange={(e) => setChA(e.target.value)} style={fld} />
          <button className="btn" style={{ padding: "3px 9px", marginLeft: 4 }} disabled={busy || chA === ""}
                  onClick={() => setLimit("set_charge_current", { amps: Number(chA) }, `nabíjecí proud ${chA} A`)}>Uložit</button>
        </div>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Vybíjecí proud (A)</label>
          <input value={disA} onChange={(e) => setDisA(e.target.value)} style={fld} />
          <button className="btn" style={{ padding: "3px 9px", marginLeft: 4 }} disabled={busy || disA === ""}
                  onClick={() => setLimit("set_discharge_current", { amps: Number(disA) }, `vybíjecí proud ${disA} A`)}>Uložit</button>
        </div>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Záložní SoC (%)</label>
          <input value={socBackup} onChange={(e) => setSocBackup(e.target.value)} style={fld} />
          <button className="btn" style={{ padding: "3px 9px", marginLeft: 4 }} disabled={busy || socBackup === ""}
                  onClick={() => setLimit("set_soc_backup", { pct: Number(socBackup) }, `záložní SoC ${socBackup} %`)}>Uložit</button>
        </div>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Force SoC (%)</label>
          <input value={socForce} onChange={(e) => setSocForce(e.target.value)} style={fld} />
          <button className="btn" style={{ padding: "3px 9px", marginLeft: 4 }} disabled={busy || socForce === ""}
                  onClick={() => setLimit("set_soc_force", { pct: Number(socForce) }, `force SoC ${socForce} %`)}>Uložit</button>
        </div>
        <div>
          <label style={{ fontSize: 12, display: "block" }}>Pracovní režim</label>
          <button className="btn" disabled={busy} onClick={() => setLimit("set_work_mode", { word: 33 }, "režim Self-Use")}>Self-Use</button>
        </div>
      </div>
      <SpotDischargePanel moduleId={mod.id} />
      <StatusLine status={status} />
    </div>
  );
}

function GoodweControl({ mod }) {
  const [mode, setMode] = useState(null);
  const [power, setPower] = useState(100);
  const [soc, setSoc] = useState(100);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = () => api.getMode(mod.id).then((r) => setMode(r.mode)).catch(() => setMode("?"));
  useEffect(() => { refresh(); }, [mod.id]);

  const send = async (body, label) => {
    if (!window.confirm(`Opravdu odeslat „${label}" do měniče ${mod.id}?`)) return;
    setBusy(true); setMsg("");
    try { const r = await api.setBatteryMode(mod.id, body); setMsg(`✓ ${r.message}`); refresh(); }
    catch (e) { setMsg(`✗ ${e.message}`); } finally { setBusy(false); }
  };
  const fld = { width: 110, padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h3 style={{ marginBottom: 2 }}>{mod.id} <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>· goodwe · režim {mode ?? "…"}</span></h3>
      <div className="row" style={{ gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginTop: 6 }}>
        <label style={{ fontSize: 12 }}>Výkon (%)<input value={power} onChange={(e) => setPower(e.target.value)} style={fld} /></label>
        <label style={{ fontSize: 12 }}>SoC cíl (%)<input value={soc} onChange={(e) => setSoc(e.target.value)} style={fld} /></label>
        <button className="btn primary" disabled={busy} onClick={() => send({ mode: "force_charge", power_pct: Number(power), target_soc: Number(soc) }, "Vynutit nabíjení")}>⚡ Nabíjet</button>
        <button className="btn" disabled={busy} onClick={() => send({ mode: "force_discharge", power_pct: Number(power), target_soc: Number(soc) }, "Vynutit vybíjení")}>🔻 Vybíjet</button>
        <button className="btn" disabled={busy} onClick={() => send({ mode: "normal" }, "Normální režim")}>⏹ Normál</button>
      </div>
      {msg && <p style={{ marginTop: 8, fontSize: 13, color: msg.startsWith("✓") ? "var(--green)" : "#e06c75" }}>{msg}</p>}
    </div>
  );
}

const ACT_LABEL = {
  charge_pv: "nabíjení z FVE", charge_grid: "nabíjení ze sítě", discharge_load: "vybíjení do domu",
  discharge_grid: "vybíjení do sítě", export: "přetok do sítě", import: "odběr ze sítě", idle: "klid",
};
const ACTIVE_LABEL = {
  force_charge: "vynucené nabíjení", force_discharge: "vybíjení do sítě",
  spiral: "spirála", set_work_mode: "změna režimu", idle: "klid",
};

function Pill({ on, children }) {
  return <span className={on ? "badge-on" : "badge-off"} style={{ fontSize: 11 }}>{children}</span>;
}

function LocalitySummary({ locId, mods }) {
  const modIds = mods.map((m) => m.id);
  const modKey = modIds.join(",");
  const [plan, setPlan] = useState(null);
  const [rules, setRules] = useState([]);
  const [outs, setOuts] = useState([]);
  const [controlled, setControlled] = useState([]);
  const [states, setStates] = useState({});

  useEffect(() => {
    if (!locId) return;
    let alive = true;
    const load = () => {
      api.getPlanner(locId).then((r) => alive && setPlan(r)).catch(() => {});
      api.listRules().then((all) => alive && setRules(all.filter((r) => modIds.includes(r.params?.target_module)))).catch(() => {});
      api.listOutputs().then((all) => alive && setOuts(all.filter((o) => o.locality_id === locId))).catch(() => {});
      api.plannerControlled().then((r) => alive && setControlled(r.devices || [])).catch(() => {});
      if (modIds.length) api.controlStates(modKey).then((r) => alive && setStates(r.states || {})).catch(() => {});
    };
    load();
    const t = setInterval(load, 10000);
    return () => { alive = false; clearInterval(t); };
  }, [locId, modKey]);

  const cfg = plan?.config; const cur = plan?.current;
  const forced = modIds.map((id) => ({ id, st: states[id] })).filter(({ st }) => st && st.action && st.action !== "idle");

  return (
    <div className="panel" style={{ marginBottom: 14, background: "color-mix(in srgb, #58a6ff 6%, transparent)", borderColor: "color-mix(in srgb, #58a6ff 30%, var(--border))" }}>
      <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8 }}>🧭 Co ovlivňuje tuto lokalitu</div>
      <div style={{ display: "grid", gap: 7, fontSize: 13, lineHeight: 1.5 }}>
        <div>
          🧠 <b>Plánovač:</b>{" "}
          {cfg?.enabled ? <Pill on>zapnutý — řídí měnič</Pill> : <Pill>vypnutý (jen poradní plán)</Pill>}
          {cur && <span className="muted"> · teď {ACT_LABEL[cur.action] || cur.action}, SoC plán {Math.round(cur.soc_pct)} %</span>}
        </div>
        {forced.length > 0 && (
          <div>⚡ <b>Aktivní zásah:</b>{" "}
            {forced.map(({ id, st }) => `${id}: ${ACTIVE_LABEL[st.action] || st.action}${st.source && st.source !== "manual" ? ` (${st.source})` : ""}`).join(", ")}
          </div>
        )}
        <div>
          📈 <b>Spotová pravidla:</b>{" "}
          {rules.length === 0 ? <span className="muted">žádné</span> : rules.map((r) => (
            <span key={r.id} style={{ marginRight: 10, whiteSpace: "nowrap" }}>
              {r.type === "spot_charge" ? "nabíjení" : "vybíjení"} „{r.id}" <Pill on={r.enabled}>{r.enabled ? "zap" : "vyp"}</Pill>
              {controlled.includes(r.params?.target_module) && <span style={{ marginLeft: 4, color: "var(--amber)", fontWeight: 700 }}>⚠ přebírá plánovač</span>}
            </span>
          ))}
          <Link to="/automation" className="muted" style={{ marginLeft: 6, fontSize: 12 }}>upravit →</Link>
        </div>
        <div>
          🔌 <b>Spínané spotřebiče:</b>{" "}
          {outs.length === 0 ? <span className="muted">žádné</span> : outs.map((o) => (
            <span key={o.id} style={{ marginRight: 10, whiteSpace: "nowrap" }}>
              {o.name} <Pill on={o.is_on}>{o.is_on ? "sepnuto" : "rozepnuto"}</Pill>{!o.enabled && <span className="muted"> (vypnuto)</span>}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function PlannerPanel({ locId }) {
  const [data, setData] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const reload = () => api.getPlanner(locId).then((r) => { setData(r); setCfg({ ...r.config }); }).catch(() => {});
  useEffect(() => { if (locId) reload(); }, [locId]);
  if (!locId || !cfg) return null;

  const set = (k, v) => setCfg({ ...cfg, [k]: v });
  const NUM = ["capacity_kwh", "soc_min_pct", "outage_reserve_pct", "max_charge_kw", "max_discharge_kw", "horizon_h"];
  const save = async () => {
    setBusy(true); setMsg("");
    const payload = { ...cfg };
    for (const k of NUM) payload[k] = cfg[k] === "" || cfg[k] == null ? null : Number(cfg[k]);
    try { await api.setPlannerConfig(locId, payload); setMsg("Uloženo a přepočítáno."); reload(); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  const cur = data?.current;
  const sched = data?.schedule || [];
  const fld = { width: 90, padding: "5px 7px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)" };
  const planImp = sched.reduce((s, r) => s + (r.import_kwh || 0), 0);
  const planExp = sched.reduce((s, r) => s + (r.export_kwh || 0), 0);

  return (
    <div className="panel" style={{ marginBottom: 14, borderColor: cfg.enabled ? "var(--green)" : "var(--border)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 700, fontSize: 14 }}>🧠 Plánovač lokality</span>
        <label style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 13, fontWeight: 600, color: cfg.enabled ? "var(--green)" : "var(--muted)" }}>
          <input type="checkbox" checked={!!cfg.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          {cfg.enabled ? "ZAPNUTÝ — řídí měnič" : "vypnutý (jen plán)"}
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12 }}>
          <input type="checkbox" checked={!!cfg.allow_grid_discharge} onChange={(e) => set("allow_grid_discharge", e.target.checked)} />
          povolit vybíjení do sítě
        </label>
      </div>
      {cfg.enabled && (
        <p className="muted" style={{ fontSize: 11.5, margin: "6px 0 0", color: "var(--amber)" }}>
          ⚠ Zapnutý plánovač <b>reálně řídí měnič</b> (přes frontu, na nastavených limitech proudu) a přebírá řízení místo reaktivních spot pravidel této lokality.
          {cfg.allow_grid_discharge ? " Vybíjení do sítě je povolené — sleduj výkon baterie/sítě." : ""}
        </p>
      )}

      <div className="row" style={{ gap: 12, flexWrap: "wrap", marginTop: 10 }}>
        <div><label style={{ fontSize: 12, display: "block" }}>Kapacita (kWh)</label><input style={fld} value={cfg.capacity_kwh ?? ""} onChange={(e) => set("capacity_kwh", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>SoC min (%)</label><input style={fld} value={cfg.soc_min_pct ?? ""} onChange={(e) => set("soc_min_pct", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>Rezerva výpadek (%)</label><input style={fld} value={cfg.outage_reserve_pct ?? ""} onChange={(e) => set("outage_reserve_pct", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>Max nabíjení (kW)</label><input style={fld} value={cfg.max_charge_kw ?? ""} onChange={(e) => set("max_charge_kw", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>Max vybíjení (kW)</label><input style={fld} value={cfg.max_discharge_kw ?? ""} onChange={(e) => set("max_discharge_kw", e.target.value)} /></div>
        <div><label style={{ fontSize: 12, display: "block" }}>Horizont (h)</label><input style={fld} value={cfg.horizon_h ?? ""} onChange={(e) => set("horizon_h", e.target.value)} /></div>
        <button className="btn primary" style={{ alignSelf: "flex-end", padding: "8px 16px" }} disabled={busy} onClick={save}>Uložit a přepočítat</button>
      </div>

      <div style={{ marginTop: 10, fontSize: 13 }}>
        {cur
          ? <span>Teď: <b>{ACT_LABEL[cur.action] || cur.action}</b> · SoC plán {Math.round(cur.soc_pct)} % <span className="muted">— {cur.reason}</span></span>
          : <span className="muted">Zatím bez plánu — potřebuje predikci výroby (zadej polohu/panely a dej Přepočítat predikci).</span>}
        {sched.length > 0 && <span className="muted"> · plán {sched.length} h, odběr {planImp.toFixed(1)} kWh, přetok {planExp.toFixed(1)} kWh</span>}
      </div>
      {msg && <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>{msg}</p>}
    </div>
  );
}

function LocalitySection({ locId, locName, mods }) {
  return (
    <section style={{ marginBottom: 24 }}>
      <h2 style={{ fontSize: 17, margin: "0 0 8px" }}>📍 {locName || "Bez lokality"}</h2>
      {locId && <LocalitySummary locId={locId} mods={mods} />}
      {locId && <PlannerPanel locId={locId} />}
      {mods.map((m) => m.adapter === "solis"
        ? <SolisControl key={m.id} mod={m} />
        : <GoodweControl key={m.id} mod={m} />)}
      {locId && <OutputsPanel locId={locId} />}
    </section>
  );
}

function HelpPanel() {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginBottom: 14 }}>
      <button className="btn" style={{ padding: "8px 16px", fontWeight: 600 }} onClick={() => setOpen(!open)}>
        {open ? "▲ Skrýt nápovědu" : "❓ Nápověda — co umí Řízení"}
      </button>
      {open && (
        <div className="panel" style={{ marginTop: 8, lineHeight: 1.55 }}>
          <p style={{ marginTop: 0 }}><b>Co je Řízení?</b> Tady se rozhoduje, jak se má baterie a měnič chovat. Dashboard jen ukazuje stav; tady do něj zasahuješ. Vše je seskupené <b>podle lokality</b> a u každé lokality jsou její <b>moduly (měniče)</b>.</p>
          <p><b>🧠 Plánovač lokality</b> — „mozek", který se sám rozhodne, kdy nabíjet a kdy vybíjet, aby ušetřil. Dívá se na předpověď výroby z FVE, na spotřebu domu a na ceny elektřiny, a podle toho:</p>
          <ul style={{ marginTop: 0 }}>
            <li>nabije baterii, když je elektřina <b>nejlevnější</b> (a počítá s tím, kolik dodá FVE),</li>
            <li>schová energii na <b>večerní špičku</b> (případně ji prodá do sítě, pokud to povolíš),</li>
            <li>vždy nechá <b>rezervu</b> pro případ výpadku sítě.</li>
          </ul>
          <p style={{ marginTop: 0 }}>Dokud je <b>vypnutý</b>, jen ukazuje plán (fialová křivka SoC v grafu na dashboardu) a nic nedělá. Když ho <b>zapneš</b>, začne měnič reálně řídit a <b>přebere řízení</b> místo jednotlivých spotových pravidel.</p>
          <p><b>🔌 Ruční řízení</b> — okamžitý zásah: „Nabíjet teď / Vybíjet teď / Stop". Po ručním povelu (i Stop) jde plánovač u tohoto modulu na <b>30 minut stranou</b>, ať tě hned nepřebije; pak se zase ujme (nebo ho nech vypnutý). Stop tedy vždy zabere.</p>
          <p><b>⚙️ Limity a režim</b> — bezpečnostní mantinely měniče: maximální nabíjecí/vybíjecí proud a hranice nabití (SoC), pod kterou se baterie nevybíjí. „Načíst aktuální z měniče" ukáže, co měnič právě má nastaveno.</p>
          <p><b>🔌 Spínané spotřebiče</b> — spínače/relé (eWeLink nebo kontakt střídače), které samy zapnou spotřebič (bojler, topnou spirálu…) podle SoC baterie nebo přebytku z FVE. Třeba „když je baterie plná a přetéká do sítě, zapni ohřev vody".</p>
          <p style={{ marginBottom: 0 }}><b>Bezpečnost:</b> každý povel se reálně zapíše do měniče, ověří zpětným čtením a zapíše do <b>auditu</b> dole. Když si nejsi jistý, začni nízkými hodnotami.</p>
        </div>
      )}
    </div>
  );
}

const AUDIT_PAGE = 50;
function AuditPanel() {
  const [rows, setRows] = useState([]);
  const [names, setNames] = useState({});
  const [open, setOpen] = useState(() => new Set());
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");      // debounced dotaz
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    Promise.all([api.controlModules().catch(() => []), api.listOutputs().catch(() => [])]).then(([ms, outs]) => {
      const map = {};
      for (const m of ms || []) map[m.id] = m.name || m.label || m.id;
      for (const o of outs || []) if (o.target) map[o.target] = o.name;
      setNames(map);
    });
  }, []);

  useEffect(() => { const t = setTimeout(() => setDq(q), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => { setPage(0); }, [dq]);
  useEffect(() => {
    let alive = true; setLoading(true);
    api.controlAudit(AUDIT_PAGE, page * AUDIT_PAGE, dq)
      .then((r) => { if (alive) { setRows(r || []); setOpen(new Set()); } })
      .catch(() => {})
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [page, dq]);

  const toggle = (id) => setOpen((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const inp = { padding: "6px 10px", borderRadius: 7, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)", fontSize: 13 };

  return (
    <div className="panel">
      <div className="row" style={{ alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>Audit povelů</h3>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="🔎 hledat (název, modul, akce, důvod, chyba…)"
          style={{ ...inp, flex: "1 1 240px", maxWidth: 360 }} />
        {q && <button className="btn" style={{ padding: "5px 10px", fontSize: 12 }} onClick={() => setQ("")}>×</button>}
      </div>
      <table style={{ marginTop: 12 }}>
        <thead><tr><th style={{ width: 18 }}></th><th>Čas</th><th>Uživatel</th><th>Modul</th><th>Akce</th><th>Co se stalo / důvod</th><th>Výsledek</th></tr></thead>
        <tbody>
          {rows.map((a) => {
            const nm = a.params?.name || names[a.module_id];
            const reason = a.params?.reason;
            const onOff = a.params?.on === true ? "zapnout" : a.params?.on === false ? "vypnout" : null;
            const isOpen = open.has(a.id);
            return (
              <Fragment key={a.id}>
                <tr onClick={() => toggle(a.id)} style={{ cursor: "pointer" }}>
                  <td className="muted" style={{ textAlign: "center" }}>{isOpen ? "▾" : "▸"}</td>
                  <td className="muted" style={{ fontSize: 12 }}>{new Date(a.time).toLocaleString("cs-CZ")}</td>
                  <td>{a.username}</td>
                  <td>{nm ? <><div style={{ fontWeight: 600 }}>{nm}</div><div className="role" style={{ fontSize: 11 }}>{a.module_id}</div></> : <span className="role">{a.module_id}</span>}</td>
                  <td>{a.action}{onOff ? ` · ${onOff}` : ""}</td>
                  <td style={{ fontSize: 12.5, maxWidth: 320 }}>{reason || <span className="muted" style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{JSON.stringify(a.params)}</span>}</td>
                  <td><span className={a.ok ? "badge-on" : "badge-off"}>{a.ok ? "OK" : "chyba"}</span>
                    {!a.ok && a.result?.error && <div style={{ fontSize: 11, marginTop: 3, color: "#e06c75" }}>{a.result.error}</div>}
                  </td>
                </tr>
                {isOpen && (
                  <tr>
                    <td></td>
                    <td colSpan={6} style={{ background: "var(--bg-2)", borderRadius: 8 }}>
                      <div style={{ padding: "8px 4px", display: "grid", gap: 8 }}>
                        {reason && <div><b>Důvod:</b> {reason}</div>}
                        {a.params?.values && (
                          <div>
                            <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 4 }}>Naměřené hodnoty v okamžiku rozhodnutí</div>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 16px" }}>
                              {Object.entries(a.params.values).map(([k, v]) => (
                                <span key={k} style={{ fontSize: 12.5 }}>
                                  <span className="muted">{k.replace(/_/g, " ")}:</span> <b>{String(v)}</b>
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                        <div>
                          <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 2 }}>Parametry</div>
                          <pre style={{ margin: 0, fontSize: 12, fontFamily: "var(--mono)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{JSON.stringify(a.params, null, 2)}</pre>
                        </div>
                        <div>
                          <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 2 }}>Výsledek</div>
                          <pre style={{ margin: 0, fontSize: 12, fontFamily: "var(--mono)", whiteSpace: "pre-wrap", wordBreak: "break-word", color: a.ok ? "var(--fg)" : "#e06c75" }}>{JSON.stringify(a.result, null, 2)}</pre>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
          {rows.length === 0 && <tr><td colSpan={7} className="muted" style={{ padding: "12px 0" }}>{loading ? "Načítám…" : (dq ? "Nic nenalezeno." : "Zatím žádné povely.")}</td></tr>}
        </tbody>
      </table>
      <div className="row" style={{ alignItems: "center", gap: 10, marginTop: 10 }}>
        <button className="btn" style={{ padding: "5px 12px", fontSize: 12 }} disabled={page === 0 || loading} onClick={() => setPage((p) => Math.max(0, p - 1))}>← Novější</button>
        <span className="muted" style={{ fontSize: 12 }}>strana {page + 1}</span>
        <button className="btn" style={{ padding: "5px 12px", fontSize: 12 }} disabled={rows.length < AUDIT_PAGE || loading} onClick={() => setPage((p) => p + 1)}>Starší →</button>
      </div>
    </div>
  );
}

export default function Control() {
  const [mods, setMods] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.controlModules().then(setMods).catch((e) => setErr(e.message));
  }, []);

  if (err) return <main><div className="panel"><p className="error">{err}</p></div></main>;
  if (!mods) return <main><p className="muted">Načítám…</p></main>;

  // seskupení podle lokality
  const byLoc = {};
  for (const m of mods) {
    const key = m.locality_id ?? "none";
    (byLoc[key] = byLoc[key] || { id: m.locality_id ?? null, name: m.locality, mods: [] }).mods.push(m);
  }
  const groups = Object.values(byLoc);

  return (
    <main>
      <HelpPanel />
      <div className="panel" style={{ marginBottom: 18, borderColor: "var(--amber)" }}>
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          ⚠ Akce zde <b>reálně zapisují do měniče</b> (přes frontu, ověřeno čtením, zaznamenáno do auditu).
          Aktuální vynucený stav vidíš i na dashboardu jako zvýrazněný pruh.
        </p>
      </div>

      {mods.length === 0 && <p className="muted">Žádný řiditelný modul.</p>}
      {groups.map((g, i) => <LocalitySection key={i} locId={g.id} locName={g.name} mods={g.mods} />)}

      <AuditPanel />
    </main>
  );
}
