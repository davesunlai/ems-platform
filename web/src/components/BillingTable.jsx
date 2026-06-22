import { useEffect, useState } from "react";
import { api } from "../api";

function fmtKWh(v) {
  return v >= 1000 ? `${(v / 1000).toFixed(2)} MWh` : `${v.toFixed(0)} kWh`;
}

export default function BillingTable({ localityId }) {
  const [b, setB] = useState(null);
  useEffect(() => {
    let alive = true;
    api.localityBilling(localityId).then((r) => alive && setB(r)).catch(() => {});
    return () => { alive = false; };
  }, [localityId]);

  if (!b || !b.configured) return null;
  const lim = b.settings.export_limit_kwh;
  const exp = b.totals.export_kwh;
  const pct = lim ? Math.min(100, (exp / lim) * 100) : 0;
  const over = lim && exp >= lim;
  const fmtMonth = (m) => {
    const [y, mo] = m.split("-");
    return new Date(y, mo - 1, 1).toLocaleDateString("cs-CZ", { month: "long", year: "numeric" });
  };

  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>Zúčtovací období</h3>
        <span className="muted" style={{ fontSize: 13 }}>
          {new Date(b.period.start).toLocaleDateString("cs-CZ")} – {new Date(b.period.end).toLocaleDateString("cs-CZ")}
        </span>
      </div>

      {lim != null && (
        <div style={{ margin: "10px 0 4px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
            <span>Přetoky za období: <strong style={{ color: over ? "#e06c75" : "var(--green)" }}>{fmtKWh(exp)}</strong></span>
            <span className="muted">limit {fmtKWh(lim)}</span>
          </div>
          <div style={{ height: 8, background: "var(--border)", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: over ? "#e06c75" : pct > 80 ? "#d29922" : "var(--green)" }} />
          </div>
        </div>
      )}

      <table style={{ marginTop: 12, width: "100%" }}>
        <thead><tr>
          <th style={{ textAlign: "left" }}>Měsíc</th>
          <th style={{ textAlign: "right" }}>Výroba</th>
          <th style={{ textAlign: "right" }}>Spotřeba</th>
          <th style={{ textAlign: "right" }}>Přetoky</th>
          <th style={{ textAlign: "right" }}>Nákup od distributora</th>
          <th style={{ textAlign: "right" }}>Cena ze sítě</th>
          <th style={{ textAlign: "right" }}>Cena do sítě</th>
        </tr></thead>
        <tbody>
          {b.baseline && (b.baseline.export_kwh || b.baseline.import_kwh) ? (
            <tr className="muted">
              <td>Před spuštěním měření</td>
              <td style={{ textAlign: "right" }}>—</td>
              <td style={{ textAlign: "right" }}>—</td>
              <td style={{ textAlign: "right" }}>{b.baseline.export_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{b.baseline.import_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>—</td>
              <td style={{ textAlign: "right" }}>—</td>
            </tr>
          ) : null}
          {b.months.map((r) => (
            <tr key={r.month}>
              <td>{fmtMonth(r.month)}</td>
              <td style={{ textAlign: "right" }}>{r.prod_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{r.cons_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right", color: "var(--green)" }}>{r.export_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{r.import_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{r.import_czk != null ? `${r.import_czk.toFixed(0)} Kč` : "—"}</td>
              <td style={{ textAlign: "right", color: "var(--green)" }}>{r.export_czk != null ? `${r.export_czk.toFixed(0)} Kč` : "—"}</td>
            </tr>
          ))}
          {!b.months.length && <tr><td colSpan="7" className="muted">Zatím žádná data v tomto období.</td></tr>}
        </tbody>
        {b.months.length > 0 && (
          <tfoot><tr style={{ fontWeight: 600, borderTop: "1px solid var(--border)" }}>
            <td>Celkem za období</td>
            <td style={{ textAlign: "right" }}>{fmtKWh(b.totals.prod_kwh)}</td>
            <td style={{ textAlign: "right" }}>{fmtKWh(b.totals.cons_kwh)}</td>
            <td style={{ textAlign: "right", color: "var(--green)" }}>{fmtKWh(b.totals.export_kwh)}</td>
            <td style={{ textAlign: "right" }}>{fmtKWh(b.totals.import_kwh)}</td>
            <td style={{ textAlign: "right" }}>{b.totals.import_czk != null ? `${b.totals.import_czk.toFixed(0)} Kč` : "—"}</td>
            <td style={{ textAlign: "right", color: "var(--green)" }}>{b.totals.export_czk != null ? `${b.totals.export_czk.toFixed(0)} Kč` : "—"}</td>
          </tr></tfoot>
        )}
      </table>
    </div>
  );
}
