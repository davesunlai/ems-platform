import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import BmsBalance from "./BmsBalance";
import BmsCellDetail from "./BmsCellDetail";

// Mapa všech článků bloku z BMS (Pylontech SC0500 po RS485): řádek = modul, buňka = článek.
// Barva = odchylka od mediánu bloku (modrá níž, oranžová výš); čísla zůstávají v běžné barvě textu.
const LOW = ["#cde2fb", "#86b6ef", "#2a78d6"], HIGH = ["#fbd9c9", "#f2a27f", "#eb6834"];
const fill = (dv, span) => {
  const a = Math.abs(dv) / Math.max(1, span);
  if (a < 0.2) return "transparent";
  const ramp = dv < 0 ? LOW : HIGH;
  return ramp[a < 0.5 ? 0 : a < 0.8 ? 1 : 2];
};
const median = (arr) => { const s = [...arr].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

const UP = "#3987e5", DOWN = "#e5484d";
/** Šipka trendu napětí článku: ▲ modrá roste, ▼ červená klesá; sytost podle rychlosti vůči nejrychlejšímu článku. */
function TrendArrow({ rate, maxUp, maxDown, size = 15 }) {
  if (rate == null) return null;
  const flat = Math.abs(rate) < 0.1;
  const rel = flat ? 0 : rate > 0 ? rate / Math.max(maxUp, 0.1) : rate / Math.min(maxDown, -0.1);
  const op = 0.45 + 0.55 * Math.min(1, rel);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: size + 3, height: size + 3, marginLeft: 4,
                   borderRadius: (size + 3) / 2, background: "var(--panel, #fff)", verticalAlign: "-2px" }}>
      <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true">
        {flat ? <rect x="3" y="5.2" width="6" height="1.6" rx="0.8" fill="var(--muted, #888)" />
          : rate > 0 ? <path d="M6 1.5 L10.5 9.5 H1.5 Z" fill={UP} fillOpacity={op} />
            : <path d="M6 10.5 L1.5 2.5 H10.5 Z" fill={DOWN} fillOpacity={op} />}
      </svg>
    </span>);
}

/** Celkový stav bloku: velká šipka nahoru modrá = nabíjení, dolů červená = vybíjení, s výkonem. */
function PowerBadge({ power, current }) {
  const w = power?.w;
  if (w == null) return null;
  const idle = Math.abs(w) < 100, chg = w > 0;
  const col = idle ? "var(--muted, #888)" : chg ? UP : DOWN;
  return (
    <span title={`výkon bloku podle ${power.source === "BMS" ? "BMS (U × I)" : "měniče"}`}
          style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "6px 16px 6px 10px", borderRadius: 14, border: `2px solid ${col}` }}>
      <svg width="34" height="34" viewBox="0 0 24 24" aria-hidden="true">
        {idle ? <circle cx="12" cy="12" r="5" fill={col} />
          : chg ? <path d="M12 2 L21 13 H15.5 V22 H8.5 V13 H3 Z" fill={col} />
            : <path d="M12 22 L3 11 H8.5 V2 H15.5 V11 H21 Z" fill={col} />}
      </svg>
      <span style={{ lineHeight: 1.15 }}>
        <span style={{ display: "block", fontSize: 12 }} className="muted">{idle ? "Baterie" : chg ? "Baterie se nabíjí" : "Baterie se vybíjí"}</span>
        <b style={{ fontSize: 22 }}>{idle ? "klid" : `${(Math.abs(w) / 1000).toFixed(2)} kW`}</b>
        {!idle && current != null && <span className="muted" style={{ fontSize: 12 }}> · {Math.abs(Number(current)).toFixed(1)} A</span>}
      </span>
    </span>);
}

/** Jedna tabulka 11 × 15: mode "mv" = napětí, "temp" = teploty. big = režim celé obrazovky (větší písmo). */
function CellTable({ c, mode, big, trend, hover, onHover, onPick, sortV }) {
  // sortV: řádky (boxy) seřazené podle celkového napětí modulu, nejvyšší nahoře; přepočítá se s každým snímkem
  const sumOf = (m) => m.mv.reduce((x, y) => x + y, 0);
  const rows = sortV ? [...c.modules].sort((a, b) => sumOf(b) - sumOf(a) || a.idx - b.idx) : c.modules;
  const sums = c.modules.map(sumOf), sMin = Math.min(...sums), sMax = Math.max(...sums), sMed = median(sums);
  const fs = big ? 15 : 10.5, pad = big ? "4px 7px" : "1px 2px";
  const temps = c.modules.flatMap((m) => m.temp);
  const tMed = temps.length ? median(temps) : 0;
  const tSpan = temps.length ? Math.max(Math.max(...temps) - tMed, tMed - Math.min(...temps), 20) : 20;   // min. rozsah 2 °C
  const vSpan = Math.max(c.max - c.median, c.median - c.min, 10);
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", fontSize: fs, fontVariantNumeric: "tabular-nums", width: big ? "100%" : undefined }}>
        <thead><tr>
          <th style={{ textAlign: "left", padding: "1px 6px 1px 0" }} className="muted">modul</th>
          {Array.from({ length: c.per_module }, (_, i) => <th key={i} className="muted" style={{ fontWeight: 400, padding: pad }}>{i + 1}</th>)}
          <th className="muted" style={{ fontWeight: 400, padding: "1px 6px" }}>{mode === "mv" ? "průměr" : "modul"}</th>
          {mode === "mv" && <th className="muted" style={{ fontWeight: 400, padding: "1px 6px" }} title="Číslo boxu a napětí modulu = součet jeho článků, na mV. Proužek = poloha mezi nejnižším a nejvyšším boxem.">box · V modulu</th>}
        </tr></thead>
        <tbody>{rows.map((m, ri) => (
          <tr key={m.idx}>
            <td style={{ padding: "1px 6px 1px 0", fontWeight: 600, whiteSpace: "nowrap" }}>{m.idx}{sortV && <span className="muted" style={{ fontWeight: 400, fontSize: "0.8em" }}> · {ri + 1}.</span>}</td>
            {(mode === "mv" ? m.mv : m.temp).map((v, i) => {
              const n = (m.idx - 1) * c.per_module + i + 1;
              const mv = m.mv[i];
              const bg = mode === "mv" ? fill(mv - c.median, vSpan) : fill(v - tMed, tSpan);
              return (
                <td key={i} title={`článek ${n} (modul ${m.idx}, pozice ${i + 1}): ${mv} mV, ${mv - c.median >= 0 ? "+" : ""}${Math.round(mv - c.median)} mV od mediánu${m.temp[i] != null ? `, ${(m.temp[i] / 10).toFixed(1)} °C` : ""}${trend && trend.rate[n - 1] != null ? `, trend ${trend.rate[n - 1] > 0 ? "+" : ""}${trend.rate[n - 1].toFixed(2)} mV/min` : ""}`}
                    onMouseEnter={onHover ? () => onHover({ n, src: "table" }) : undefined} onMouseLeave={onHover ? () => onHover(null) : undefined}
                    onClick={onPick ? () => onPick(n) : undefined}
                    style={{ padding: pad, textAlign: "right", border: "1px solid var(--panel, #fff)", borderRadius: 3,
                             cursor: onPick ? "pointer" : undefined, position: "relative",
                             outline: hover?.n === n ? "2.5px solid var(--fg)" : undefined, outlineOffset: -2, zIndex: hover?.n === n ? 2 : undefined,
                             background: bg, color: bg === "transparent" ? undefined : "#0b0b0b",
                             fontWeight: mode === "mv" && (n === c.nmin || n === c.nmax) ? 700 : 400 }}>
                  {mode === "mv" ? v : (v / 10).toFixed(big ? 1 : 0)}
                  {mode === "mv" && trend && <TrendArrow rate={trend.rate[n - 1]} maxUp={trend.max_up} maxDown={trend.max_down} />}
                </td>);
            })}
            <td style={{ padding: "1px 6px", textAlign: "right" }}>{mode === "mv" ? m.avg.toFixed(0) : (m.temp_module != null ? `${m.temp_module.toFixed(1)} °C` : "—")}</td>
            {mode === "mv" && (() => {             // číslo boxu + napětí modulu na mV + proužek polohy mezi nejnižším a nejvyšším boxem
              const sv = sumOf(m), rel = sMax > sMin ? (sv - sMin) / (sMax - sMin) : 0.5, hi = sv >= sMed;
              const col = hi ? HIGH[2] : LOW[2];
              return (
                <td style={{ padding: big ? "3px 8px" : "1px 6px", whiteSpace: "nowrap" }}
                    title={`box ${m.idx}: součet napětí ${m.mv.length} článků = ${(sv / 1000).toFixed(3)} V, ${sv - sMed >= 0 ? "+" : ""}${Math.round(sv - sMed)} mV od mediánu boxů${m.voltage != null ? ` · BMS hlásí modul ${m.voltage.toFixed(2)} V (rozlišení 10 mV)` : ""}`}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: big ? 8 : 5 }}>
                    <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: big ? 30 : 20, height: big ? 22 : 15, padding: "0 5px",
                                   borderRadius: 999, background: col, color: "#fff", fontWeight: 800, fontSize: big ? 13 : 9.5, lineHeight: 1 }}>{m.idx}</span>
                    <span style={{ display: "inline-block", textAlign: "right" }}>
                      <span style={{ display: "block", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{(sv / 1000).toFixed(3)}</span>
                      <span style={{ display: "block", height: big ? 4 : 3, width: big ? 76 : 46, borderRadius: 2, background: "var(--border, #ddd)", position: "relative", marginTop: 1 }}>
                        <i style={{ position: "absolute", top: 0, bottom: 0, left: 0, width: `${Math.max(6, rel * 100)}%`, borderRadius: 2, background: col, transition: "width .6s ease" }} />
                      </span>
                    </span>
                  </span>
                </td>); })()}
          </tr>))}</tbody>
      </table>
    </div>);
}

const Legend = ({ what, med }) => (
  <span>Podbarvení = odchylka od mediánu bloku ({med}): <span style={{ background: LOW[1], color: "#0b0b0b", padding: "0 5px", borderRadius: 3 }}>níž</span> · <span style={{ background: HIGH[1], color: "#0b0b0b", padding: "0 5px", borderRadius: 3 }}>výš</span>{what}</span>);

export default function BmsCells({ locId }) {
  const [data, setData] = useState(null);
  const [mode, setMode] = useState("mv");
  const [full, setFull] = useState(null);             // module_id zobrazený přes celou obrazovku
  const [bal, setBal] = useState(false);              // panel ⚖ balancování v celoobrazovkovém zobrazení
  const [now, setNow] = useState(Date.now());
  const [period, setPeriod] = useState({});          // skutečný rozestup mezi posledními dvěma snímky, podle modulu
  const [hover, setHover] = useState(null);           // {n, src} článek pod myší (tabulka ↔ seřazený seznam se zvýrazňují navzájem)
  const [sel, setSel] = useState(null);               // číslo článku s otevřeným detailem
  const histRef = useRef({});                         // modul → živé snímky po dobu otevřeného okna [{t, mv[], soc, pw}]
  const [sortV, setSortV] = useState(false);          // řádky tabulek seřazené podle napětí boxu (živě)
  const [balRun, setBalRun] = useState({});          // modul → běží ⚖ balancování (čtení po 5 s pak nezávisí na otevřeném okně)
  // Živé sledování: dokud je okno otevřené, hlásíme to serveru (EMSBOX pak čte články po pár sekundách) a dotahujeme po 5 s.
  useEffect(() => {
    let alive = true;
    const seen = {};
    const load = () => api.bmsLocality(locId).then((r) => {
      if (!alive) return;
      (r || []).forEach((b) => {
        const t = b.cells ? Date.parse(b.cells.time) : null;
        if (t && seen[b.module_id] && t > seen[b.module_id]) setPeriod((p) => ({ ...p, [b.module_id]: (t - seen[b.module_id]) / 1000 }));
        if (t && t !== seen[b.module_id]) {            // nový snímek → do živé historie (dočasný graf, detail článku)
          const h = (histRef.current[b.module_id] ||= []);
          h.push({ t, mv: b.cells.modules.flatMap((m) => m.mv), soc: b.summary?.bms_soc ?? null, pw: b.power?.w ?? null });
          if (h.length > 3000) h.splice(0, h.length - 3000);
        }
        if (t) seen[b.module_id] = t;
        api.bmsLive(b.module_id).catch(() => {});
        api.balActive(b.module_id).then((x) => alive && setBalRun((m) => (!!m[b.module_id] === !!x ? m : { ...m, [b.module_id]: !!x }))).catch(() => {});
      });
      setData(r || []);
    }).catch(() => alive && setData([]));
    load();
    const t = setInterval(load, 5000);
    const t2 = setInterval(() => setNow(Date.now()), 1000);
    return () => { alive = false; clearInterval(t); clearInterval(t2); };
  }, [locId]);
  useEffect(() => {
    if (!full) return undefined;
    const onKey = (e) => { if (e.key !== "Escape") return; if (sel != null) setSel(null); else setFull(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full, sel]);
  if (!data || !data.length) return null;

  const liveBar = (b, c) => {
    const age = Math.max(0, (now - Date.parse(c.time)) / 1000);
    const per = period[b.module_id] || b.live?.period_s || 5;
    const fresh = age < Math.max(15, per * 3);
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, margin: "0 0 5px" }}>
        <span style={{ width: 8, height: 8, borderRadius: 4, background: fresh ? "#0ca30c" : "#fab219", flex: "0 0 auto" }} />
        <span>{fresh
          ? <><b>Živě</b> — napětí článků se čtou každých {per < 9.5 ? per.toFixed(0) : Math.round(per)} s{balRun[b.module_id]
            ? <> — <b>běží ⚖ balancování</b>, čtení pokračuje i po zavření okna až do jeho konce</>
            : ", jen dokud je toto okno otevřené"}</>
          : <><b>Čekám na živá data z boxu…</b> poslední snímek je {age < 90 ? `${Math.round(age)} s` : `${Math.round(age / 60)} min`} starý</>}</span>
        <span className="muted" style={{ marginLeft: "auto", whiteSpace: "nowrap" }}>{fresh ? `další čtení za ${Math.max(0, Math.ceil(per - age))} s` : ""}</span>
        {fresh && <span className="bms-bar" title="čas do dalšího čtení" style={{ width: 90, height: 5, borderRadius: 3, background: "var(--border, #ddd)", overflow: "hidden", flex: "0 0 auto" }}>
          <i key={c.time} style={{ display: "block", height: "100%", background: "#2a78d6", animation: `bmsfill ${per}s linear forwards` }} />
        </span>}
      </div>);
  };
  const head = (c, s) => (
    <span className="muted" style={{ fontSize: 11.5 }}>
      {c.count} článků · min {c.min} mV (č. {c.nmin}) · max {c.max} mV (č. {c.nmax}) · rozptyl {c.delta} mV
      {s.bms_soc != null ? ` · SoC ${Math.round(s.bms_soc)} %` : ""}{s.bms_voltage != null ? ` · ${Number(s.bms_voltage).toFixed(1)} V` : ""}
      {s.bms_current != null ? ` · ${Number(s.bms_current).toFixed(1)} A` : ""}
      {" · "}{new Date(c.time).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
    </span>);
  const fb = full ? data.find((b) => b.module_id === full && b.cells) : null;

  return (
    <div style={{ marginTop: 12 }}>
      <style>{`@keyframes bmsfill { from { width: 0% } to { width: 100% } }
        @media (prefers-reduced-motion: reduce) { .bms-bar > i { animation: none !important; width: 100% !important; } }`}</style>
      {data.map((b) => {
        const c = b.cells, s = b.summary || {};
        if (!c) return <p key={b.module_id} className="muted" style={{ fontSize: 12 }}>🔬 BMS {b.name}: zatím žádná data článků.</p>;
        return (
          <div key={b.module_id} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 6 }}>
              <b style={{ fontSize: 13 }}>🔬 Články {b.block_idx ? `B${b.block_idx}` : b.name} (BMS)</b>
              <button className="btn" onClick={() => setFull(b.module_id)} title="Napětí i teploty všech článků přes celou obrazovku"
                      style={{ marginLeft: "auto", background: "#2a78d6", color: "#fff", fontWeight: 800, padding: "7px 14px", fontSize: 13.5, borderRadius: 10 }}>
                ⛶ Zvětšit na celou obrazovku
              </button>
            </div>
            <div style={{ marginBottom: 4 }}>{head(c, s)}</div>
            {liveBar(b, c)}
            <CellTable c={c} mode={mode} />
            <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>
              <a href="#" onClick={(e) => { e.preventDefault(); setMode(mode === "mv" ? "temp" : "mv"); }}>{mode === "mv" ? "zobrazit teploty" : "zobrazit napětí"}</a>{" · "}
              {mode === "mv" ? <><Legend med={`${c.median} mV`} what=". Tučně nejnižší a nejvyšší článek." /></> : "Teploty u článků ve °C, obnovují se 1× za minutu."}
              {" "}Do historie se ukládá 1× za 5 min, při testu baterie 1× za min.
            </div>
          </div>);
      })}

      {fb && (() => { const c = fb.cells, s = fb.summary || {}; return (
        <div style={{ position: "fixed", inset: 0, zIndex: 200, background: "var(--panel, var(--bg, #fff))", color: "var(--fg, #111)", overflow: "auto", padding: "14px 18px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
            <b style={{ fontSize: 19 }}>🔬 Články {fb.block_idx ? `B${fb.block_idx}` : fb.name} (BMS)</b>
            <PowerBadge power={fb.power} current={s.bms_current} />
            {(() => {                                  // napětí celých bloků vedle sebe (z BMS; jinak součet článků)
              const packs = data.map((b) => ({ id: b.module_id, lab: b.block_idx ? `B${b.block_idx}` : b.name,
                v: b.summary?.bms_voltage ?? (b.cells ? b.cells.modules.reduce((x, m) => x + m.mv.reduce((y, z) => y + z, 0), 0) / 1000 : null),
                n: b.cells?.count, soc: b.summary?.bms_soc })).filter((x) => x.v != null);
              if (!packs.length) return null;
              const fv = (v) => Number(v).toLocaleString("cs-CZ", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
              return (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 14, padding: "4px 12px", border: "1px solid var(--border)", borderRadius: 10 }}
                      title="Napětí celého bloku podle BMS. Bloky s různým počtem článků mají různé napětí i při stejném stavu — proto je pod ním i průměr na článek.">
                  {packs.map((x) => <span key={x.id} style={{ lineHeight: 1.15, opacity: x.id === fb.module_id ? 1 : 0.8 }}>
                    <span className="muted" style={{ display: "block", fontSize: 12 }}>Napětí {x.lab}{x.id === fb.module_id ? " (tento)" : ""}</span>
                    <b style={{ fontSize: 20, fontVariantNumeric: "tabular-nums" }}>{fv(x.v)} V</b>
                    <span className="muted" style={{ fontSize: 12 }}>{x.n ? ` · ${(x.v / x.n).toLocaleString("cs-CZ", { minimumFractionDigits: 3, maximumFractionDigits: 3 })} V/čl.` : ""}{x.soc != null ? ` · ${Math.round(x.soc)} %` : ""}</span>
                  </span>)}
                  {packs.length === 2 && <span style={{ lineHeight: 1.15 }}>
                    <span className="muted" style={{ display: "block", fontSize: 12 }}>Rozdíl</span>
                    <b style={{ fontSize: 20, fontVariantNumeric: "tabular-nums" }}>{fv(Math.abs(packs[0].v - packs[1].v))} V</b></span>}
                </span>);
            })()}
            <button className="btn" onClick={() => setBal(!bal)} title="Řízené cyklické nabíjení a vybíjení podle rozpětí napětí článků"
                    style={{ fontWeight: 800, padding: "8px 16px", fontSize: 14, borderRadius: 10, background: bal ? "var(--border)" : "#2a78d6", color: bal ? "var(--fg)" : "#fff" }}>⚖ Balancování</button>
            <button className="btn" onClick={() => setFull(null)} style={{ marginLeft: "auto", fontWeight: 800, padding: "8px 16px", fontSize: 14, borderRadius: 10 }}>✕ Zavřít (Esc)</button>
          </div>
          <div style={{ marginBottom: 6 }}>{head(c, s)}</div>
          {liveBar(fb, c)}
          <BmsBalance key={fb.module_id} block={fb} open={bal} setOpen={setBal} hover={hover} onHover={setHover} onPick={setSel} localHist={histRef.current[fb.module_id]} />
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", margin: "10px 0 4px" }}>
            <h3 style={{ fontSize: 15, margin: 0 }}>Napětí článků (mV)</h3>
            <button className="btn" onClick={() => setSortV(!sortV)} title="Řádky (boxy) se průběžně řadí podle součtu napětí článků, nejvyšší nahoře. Platí pro tabulku napětí i teplot."
                    style={{ fontWeight: 800, padding: "7px 16px", fontSize: 14, borderRadius: 10, background: sortV ? "#eb6834" : "#2a78d6", color: "#fff" }}>
              {sortV ? "● Řazeno podle napětí boxu (živě) — vrátit pořadí 1, 2, 3…" : "⇅ Seřadit boxy podle celkového napětí"}</button>
            {sortV && <span className="muted" style={{ fontSize: 12 }}>nejvyšší napětí nahoře · číslo za tečkou = pořadí · rozdíl mezi prvním a posledním boxem {(() => { const v = c.modules.map((m) => m.mv.reduce((x, y) => x + y, 0)); return (Math.max(...v) - Math.min(...v)).toLocaleString("cs-CZ"); })()} mV</span>}
          </div>
          <CellTable c={c} mode="mv" big trend={fb.trend} hover={hover} onHover={setHover} onPick={setSel} sortV={sortV} />
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}><Legend med={`${c.median} mV`} what=". Tučně nejnižší a nejvyšší článek. Poslední sloupec = číslo boxu a součet napětí jeho článků na mV; proužek ukazuje, kde box leží mezi nejnižším a nejvyšším (oranžová nad mediánem boxů, modrá pod). Najetím se článek zvýrazní i v seřazeném seznamu, kliknutím se otevře jeho průběh." /></div>
          <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
            {fb.trend
              ? <>Šipka u článku = změna jeho napětí za posledních {fb.trend.samples} snímků ({fb.trend.window_s < 120 ? `${fb.trend.window_s} s` : `${Math.round(fb.trend.window_s / 60)} min`}):{" "}
                  <TrendArrow rate={1} maxUp={1} maxDown={-1} /> roste · <TrendArrow rate={-1} maxUp={1} maxDown={-1} /> klesá · <TrendArrow rate={0} maxUp={1} maxDown={-1} /> beze změny.
                  Sytější šipka = rychlejší změna; nejrychleji teď roste +{fb.trend.max_up.toFixed(2)} mV/min, nejrychleji klesá {fb.trend.max_down.toFixed(2)} mV/min.</>
              : "Šipky trendu článků se objeví po několika snímcích (do ~20 s od otevření okna)."}
          </div>
          <h3 style={{ fontSize: 15, margin: "18px 0 4px" }}>Teploty u článků (°C)</h3>
          <CellTable c={c} mode="temp" big hover={hover} onHover={setHover} onPick={setSel} sortV={sortV} />
          {sel != null && <BmsCellDetail block={fb} n={sel} hist={histRef.current[fb.module_id]} onClose={() => setSel(null)} />}
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}><Legend med={`${(median(c.modules.flatMap((m) => m.temp)) / 10).toFixed(1)} °C`} what=". Teploty se živě nečtou, obnovují se 1× za minutu. Poslední sloupec = teplota modulu." /></div>
        </div>); })()}
    </div>);
}
