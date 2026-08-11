import { Fragment, useEffect, useState } from "react";
import { api } from "../api";

function fmtKWh(v) {
  return v >= 1000 ? `${(v / 1000).toFixed(2)} MWh` : `${v.toFixed(0)} kWh`;
}

export default function BillingTable({ localityId }) {
  const [b, setB] = useState(null);
  const [openMonth, setOpenMonth] = useState(null);
  const [days, setDays] = useState({});
  const toggleMonth = (m) => {
    if (openMonth === m) { setOpenMonth(null); return; }
    setOpenMonth(m);
    if (!days[m]) {
      api.localityBillingDays(localityId, m)
        .then((r) => setDays((x) => ({ ...x, [m]: r.days || [] })))
        .catch(() => setDays((x) => ({ ...x, [m]: [] })));
    }
  };
  useEffect(() => {
    let alive = true;
    api.localityBilling(localityId).then((r) => alive && setB(r)).catch(() => {});
    return () => { alive = false; };
  }, [localityId]);

  if (!b || !b.configured) return null;
  const s = b.settings;
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
          <th style={{ textAlign: "right" }}>Saldo</th>
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
              <td style={{ textAlign: "right" }}>—</td>
            </tr>
          ) : null}
          {b.months.map((r) => (<Fragment key={r.month}>
            <tr onClick={() => toggleMonth(r.month)} style={{ cursor: "pointer" }}
                title="Klikni pro denní rozpad">
              <td><span style={{ fontSize: 10, opacity: 0.7, marginRight: 4 }}>{openMonth === r.month ? "▾" : "▸"}</span>{fmtMonth(r.month)}</td>
              <td style={{ textAlign: "right" }}>{r.prod_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{r.cons_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right", color: "var(--green)" }}>{r.export_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{r.import_kwh.toFixed(0)} kWh</td>
              <td style={{ textAlign: "right" }}>{r.import_czk != null ? `${r.import_czk.toFixed(0)} Kč` : "—"}</td>
              <td style={{ textAlign: "right", color: "var(--green)" }}>{r.export_czk != null ? `${r.export_czk.toFixed(0)} Kč` : "—"}</td>
              <td style={{ textAlign: "right", fontWeight: 600, color: (r.saldo_czk || 0) >= 0 ? "var(--green)" : "#e06c75" }}>
                {r.saldo_czk != null ? `${r.saldo_czk > 0 ? "+" : ""}${r.saldo_czk.toFixed(0)} Kč` : "—"}
              </td>
            </tr>
            {openMonth === r.month && !days[r.month] && (
              <tr><td colSpan="8" className="muted" style={{ fontSize: 12 }}>Načítám dny…</td></tr>
            )}
            {openMonth === r.month && days[r.month] && days[r.month].map((d) => (
              <tr key={d.day} style={{ fontSize: 12, opacity: 0.92, background: "var(--bg)" }}>
                <td style={{ paddingLeft: 22 }}>{new Date(d.day).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric", weekday: "short" })}</td>
                <td style={{ textAlign: "right" }}>
                  {d.pv_kwh != null ? `${d.pv_kwh.toFixed(0)} kWh` : "—"}
                  {d.pv_forecast_kwh != null && <span className="muted" title="predikce výroby pro ten den"> (☀️ {d.pv_forecast_kwh.toFixed(0)})</span>}
                </td>
                <td style={{ textAlign: "right" }}>{d.cons_kwh != null ? `${d.cons_kwh.toFixed(0)} kWh` : "—"}</td>
                <td style={{ textAlign: "right", color: "var(--green)" }}>{d.export_kwh.toFixed(1)} kWh</td>
                <td style={{ textAlign: "right" }}>{d.import_kwh.toFixed(1)} kWh</td>
                <td style={{ textAlign: "right" }}>{d.import_czk.toFixed(0)} Kč</td>
                <td style={{ textAlign: "right", color: "var(--green)" }}>{d.export_czk.toFixed(0)} Kč</td>
                <td style={{ textAlign: "right", color: (d.saldo_czk || 0) >= 0 ? "var(--green)" : "#e06c75" }}>
                  {`${d.saldo_czk > 0 ? "+" : ""}${d.saldo_czk.toFixed(0)} Kč`}
                </td>
              </tr>
            ))}
          </Fragment>))}
          {!b.months.length && <tr><td colSpan="8" className="muted">Zatím žádná data v tomto období.</td></tr>}
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
            <td style={{ textAlign: "right", color: (b.totals.saldo_czk || 0) >= 0 ? "var(--green)" : "#e06c75" }}>
              {b.totals.saldo_czk != null ? `${b.totals.saldo_czk > 0 ? "+" : ""}${b.totals.saldo_czk.toFixed(0)} Kč` : "—"}
            </td>
          </tr></tfoot>
        )}
      </table>

      <p className="muted" style={{ fontSize: 11.5, marginTop: 8, lineHeight: 1.5 }}>
        {s.pricing_mode === "tariff"
          ? <>Ceny z pevného tarifu lokality ({s.tariff_import_czk} / {s.tariff_export_czk} Kč/kWh).</>
          : <>Ceny podle <b>sazebníku lokality</b> (stejný model jako plánovač):
              nákup = spot {s.spot_buy_surcharge ? `+ ${s.spot_buy_surcharge} Kč/MWh přirážka` : ""} + distribuce + poplatky;
              prodej = spot {s.spot_sell_fee ? `− ${s.spot_sell_fee} Kč/MWh provize` : ""}.</>}
        {" "}<b>Saldo</b> = do sítě − ze sítě (kladné = dodal jsi víc, než odebral).
        {b.fees_czk ? <> Paušály za období <b>{b.fees_czk.toFixed(0)} Kč</b> (nejsou v saldu).</> : null}
        {" "}Pozor: měření je z měniče, faktura dodavatele z fakturačního elektroměru — malý rozdíl je normální.
      </p>
    </div>
  );
}
