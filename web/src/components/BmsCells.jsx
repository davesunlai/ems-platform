import { useEffect, useState } from "react";
import { api } from "../api";

// Mapa všech článků bloku z BMS (Pylontech SC0500 po RS485): řádek = modul, buňka = článek.
// Barva = odchylka napětí článku od mediánu bloku (modrá níž, oranžová výš); čísla zůstávají v běžné barvě textu.
const LOW = ["#cde2fb", "#86b6ef", "#2a78d6"], HIGH = ["#fbd9c9", "#f2a27f", "#eb6834"];
const fill = (dv, span) => {
  const a = Math.abs(dv) / Math.max(10, span);
  if (a < 0.2) return "transparent";
  const ramp = dv < 0 ? LOW : HIGH;
  return ramp[a < 0.5 ? 0 : a < 0.8 ? 1 : 2];
};

export default function BmsCells({ locId }) {
  const [data, setData] = useState(null);
  const [mode, setMode] = useState("mv");
  const [now, setNow] = useState(Date.now());
  const [period, setPeriod] = useState({});          // skutečný rozestup mezi posledními dvěma snímky, podle modulu
  // Živé sledování: dokud je okno otevřené, hlásíme to serveru (EMSBOX pak čte články po pár sekundách) a dotahujeme po 5 s.
  useEffect(() => {
    let alive = true;
    const seen = {};
    const load = () => api.bmsLocality(locId).then((r) => {
      if (!alive) return;
      (r || []).forEach((b) => {
        const t = b.cells ? Date.parse(b.cells.time) : null;
        if (t && seen[b.module_id] && t > seen[b.module_id]) setPeriod((p) => ({ ...p, [b.module_id]: (t - seen[b.module_id]) / 1000 }));
        if (t) seen[b.module_id] = t;
        api.bmsLive(b.module_id).catch(() => {});
      });
      setData(r || []);
    }).catch(() => alive && setData([]));
    load();
    const t = setInterval(load, 5000);
    const t2 = setInterval(() => setNow(Date.now()), 1000);
    return () => { alive = false; clearInterval(t); clearInterval(t2); };
  }, [locId]);
  if (!data || !data.length) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <style>{`@keyframes bmsfill { from { width: 0% } to { width: 100% } }
        @media (prefers-reduced-motion: reduce) { .bms-bar > i { animation: none !important; width: 100% !important; } }`}</style>
      {data.map((b) => {
        const c = b.cells, s = b.summary || {};
        if (!c) return <p key={b.module_id} className="muted" style={{ fontSize: 12 }}>🔬 BMS {b.name}: zatím žádná data článků.</p>;
        const span = Math.max(c.max - c.median, c.median - c.min);
        return (
          <div key={b.module_id} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
              <b style={{ fontSize: 13 }}>🔬 Články {b.block_idx ? `B${b.block_idx}` : b.name} (BMS)</b>
              <span className="muted" style={{ fontSize: 11.5 }}>
                {c.count} článků · min {c.min} mV (č. {c.nmin}) · max {c.max} mV (č. {c.nmax}) · rozptyl {c.delta} mV
                {s.bms_soc != null ? ` · SoC ${Math.round(s.bms_soc)} %` : ""}{s.bms_voltage != null ? ` · ${Number(s.bms_voltage).toFixed(1)} V` : ""}
                {" · "}{new Date(c.time).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}
              </span>
              <span style={{ marginLeft: "auto", fontSize: 11.5 }}>
                <a href="#" onClick={(e) => { e.preventDefault(); setMode(mode === "mv" ? "temp" : "mv"); }}>{mode === "mv" ? "zobrazit teploty" : "zobrazit napětí"}</a>
              </span>
            </div>
            {(() => {
              const age = Math.max(0, (now - Date.parse(c.time)) / 1000);
              const per = period[b.module_id] || b.live?.period_s || 5;
              const fresh = age < Math.max(15, per * 3);
              return (
                <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, margin: "0 0 5px" }}>
                  <span style={{ width: 8, height: 8, borderRadius: 4, background: fresh ? "#0ca30c" : "#fab219", flex: "0 0 auto" }} />
                  <span>{fresh
                    ? <><b>Živě</b> — články se čtou každých {per < 9.5 ? per.toFixed(0) : Math.round(per)} s, jen dokud je toto okno otevřené</>
                    : <><b>Čekám na živá data z boxu…</b> poslední snímek je {age < 90 ? `${Math.round(age)} s` : `${Math.round(age / 60)} min`} starý</>}</span>
                  <span className="muted" style={{ marginLeft: "auto", whiteSpace: "nowrap" }}>{fresh ? `další čtení za ${Math.max(0, Math.ceil(per - age))} s` : ""}</span>
                  {fresh && <span className="bms-bar" title="čas do dalšího čtení" style={{ width: 90, height: 5, borderRadius: 3, background: "var(--border, #ddd)", overflow: "hidden", flex: "0 0 auto" }}>
                    <i key={c.time} style={{ display: "block", height: "100%", background: "#2a78d6", animation: `bmsfill ${per}s linear forwards` }} />
                  </span>}
                </div>);
            })()}
            <div style={{ overflowX: "auto" }}>
              <table style={{ borderCollapse: "collapse", fontSize: 10.5, fontVariantNumeric: "tabular-nums" }}>
                <thead><tr>
                  <th style={{ textAlign: "left", padding: "1px 6px 1px 0" }} className="muted">modul</th>
                  {Array.from({ length: c.per_module }, (_, i) => <th key={i} className="muted" style={{ fontWeight: 400, padding: "1px 3px" }}>{i + 1}</th>)}
                  <th className="muted" style={{ fontWeight: 400, padding: "1px 6px" }}>{mode === "mv" ? "průměr" : "modul"}</th>
                  <th className="muted" style={{ fontWeight: 400, padding: "1px 6px" }}>V</th>
                </tr></thead>
                <tbody>{c.modules.map((m) => (
                  <tr key={m.idx}>
                    <td style={{ padding: "1px 6px 1px 0", fontWeight: 600 }}>{m.idx}</td>
                    {(mode === "mv" ? m.mv : m.temp).map((v, i) => {
                      const n = (m.idx - 1) * c.per_module + i + 1;
                      const mv = m.mv[i];
                      return (
                        <td key={i} title={`článek ${n} (modul ${m.idx}, pozice ${i + 1}): ${mv} mV, ${mv - c.median >= 0 ? "+" : ""}${Math.round(mv - c.median)} mV od mediánu${m.temp[i] != null ? `, ${(m.temp[i] / 10).toFixed(1)} °C` : ""}`}
                            style={{ padding: "1px 2px", textAlign: "right", border: "1px solid var(--bg, #fff)", borderRadius: 3,
                                     background: mode === "mv" ? fill(mv - c.median, span) : "transparent",
                                     fontWeight: n === c.nmin || n === c.nmax ? 700 : 400 }}>
                          {mode === "mv" ? v : (v / 10).toFixed(0)}
                        </td>);
                    })}
                    <td style={{ padding: "1px 6px", textAlign: "right" }}>{mode === "mv" ? m.avg.toFixed(0) : (m.temp_module != null ? `${m.temp_module.toFixed(1)} °C` : "—")}</td>
                    <td style={{ padding: "1px 6px", textAlign: "right" }}>{m.voltage != null ? m.voltage.toFixed(2) : "—"}</td>
                  </tr>))}</tbody>
              </table>
            </div>
            <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>
              Do historie se ukládá 1× za 5 min, při testu baterie 1× za min — živé čtení ukládání nemění.{" "}
              {mode === "mv" ? <>Napětí v mV. Podbarvení = odchylka od mediánu bloku ({c.median} mV): <span style={{ background: LOW[1], padding: "0 5px", borderRadius: 3 }}>níž</span> · <span style={{ background: HIGH[1], padding: "0 5px", borderRadius: 3 }}>výš</span>. Tučně nejnižší a nejvyšší článek.</> : "Teploty u článků ve °C. Teploty se živě nečtou — obnovují se 1× za minutu."}
            </div>
          </div>);
      })}
    </div>);
}
