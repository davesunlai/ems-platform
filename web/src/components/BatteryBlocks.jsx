// Bateriové bloky měniče (B1, B2, …): jmenovitá kapacita a popis každého bloku. Součet se propíše do kapacity plánovače lokality.
import { useEffect, useState } from "react";
import { api } from "../api";

const FLD = { padding: "4px 6px", borderRadius: 6, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--fg)", width: "100%", boxSizing: "border-box" };
const EMPTY = { name: "", capacity_kwh: "", modules_count: "", module_model: "", module_kwh: "", cells_per_module: "", installed: "", note: "" };

export default function BatteryBlocks({ moduleId, packs }) {
  const [rows, setRows] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.btBlocks(moduleId).then((r) => setRows(r.map((b) => ({ ...EMPTY, ...b })))).catch((e) => setMsg(e.message)); }, [moduleId]);
  if (!rows) return null;
  const set = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const capOf = (r) => (r.capacity_kwh !== "" && r.capacity_kwh != null ? Number(r.capacity_kwh) : (r.modules_count && r.module_kwh ? Number(r.modules_count) * Number(r.module_kwh) : 0));
  const total = rows.reduce((s, r) => s + (capOf(r) || 0), 0);
  const add = () => setRows([...rows, { ...EMPTY, name: `B${rows.length + 1}`, module_model: rows[0]?.module_model || "", module_kwh: rows[0]?.module_kwh || "", cells_per_module: rows[0]?.cells_per_module || "" }]);
  const save = async () => {
    setBusy(true); setMsg("");
    try {
      const out = await api.btBlocksSave(moduleId, rows.map((r) => ({ ...r, capacity_kwh: capOf(r) || null, modules_count: r.modules_count === "" ? null : Number(r.modules_count),
        module_kwh: r.module_kwh === "" ? null : Number(r.module_kwh), cells_per_module: r.cells_per_module === "" ? null : Number(r.cells_per_module) })));
      setRows(out.map((b) => ({ ...EMPTY, ...b }))); setMsg(`Uloženo · celkem ${out.reduce((s, b) => s + Number(b.capacity_kwh), 0).toFixed(2)} kWh (propsáno do kapacity plánovače).`);
    } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  return (
    <div style={{ flexBasis: "100%", marginTop: 8, border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <b style={{ fontSize: 13 }}>🔋 Bateriové bloky</b>
        <span className="muted" style={{ fontSize: 11.5 }}>
          jeden blok = jeden bateriový vstup měniče (B1 ↔ battery_*_1 …){packs ? ` · měnič hlásí ${packs}` : ""} · celkem <b>{total.toFixed(2)} kWh</b>
        </span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button type="button" className="btn" onClick={add}>+ přidat blok</button>
          <button type="button" className="btn" disabled={busy || !rows.length} onClick={save}>💾 Uložit bloky</button>
        </span>
      </div>
      {rows.length === 0 && <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>Bez bloků se celková kapacita plánovače dělí rovnoměrně podle počtu baterií. Zadej bloky, aby test počítal SoH pro každou baterii zvlášť.</p>}
      {rows.length > 0 && (
        <table style={{ width: "100%", fontSize: 12, marginTop: 6 }}>
          <thead><tr><th>#</th><th>název</th><th>modulů</th><th>model modulu</th><th>kWh / modul</th><th>článků / modul</th><th>kapacita kWh</th><th>instalace / stáří</th><th>poznámka</th><th></th></tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={i}>
              <td className="muted">B{i + 1}</td>
              <td style={{ width: 70 }}><input style={FLD} value={r.name} placeholder={`B${i + 1}`} onChange={(e) => set(i, "name", e.target.value)} /></td>
              <td style={{ width: 60 }}><input style={FLD} type="number" value={r.modules_count} onChange={(e) => set(i, "modules_count", e.target.value)} /></td>
              <td><input style={FLD} value={r.module_model} placeholder="Pylontech H48050" onChange={(e) => set(i, "module_model", e.target.value)} /></td>
              <td style={{ width: 80 }}><input style={FLD} type="number" step="0.01" value={r.module_kwh} placeholder="2.4" onChange={(e) => set(i, "module_kwh", e.target.value)} /></td>
              <td style={{ width: 70 }}><input style={FLD} type="number" value={r.cells_per_module} placeholder="15" onChange={(e) => set(i, "cells_per_module", e.target.value)} /></td>
              <td style={{ width: 90 }}><input style={{ ...FLD, fontWeight: 600 }} type="number" step="0.01" value={r.capacity_kwh} placeholder={r.modules_count && r.module_kwh ? (Number(r.modules_count) * Number(r.module_kwh)).toFixed(2) : ""} onChange={(e) => set(i, "capacity_kwh", e.target.value)} /></td>
              <td style={{ width: 120 }}><input style={FLD} value={r.installed} placeholder="2023 (cca 3 roky)" onChange={(e) => set(i, "installed", e.target.value)} /></td>
              <td><input style={FLD} value={r.note} onChange={(e) => set(i, "note", e.target.value)} /></td>
              <td><button type="button" className="btn" style={{ padding: "1px 7px" }} title="odebrat blok" onClick={() => setRows(rows.filter((_, j) => j !== i))}>✕</button></td>
            </tr>))}
          </tbody></table>)}
      {msg && <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{msg}</p>}
    </div>
  );
}
