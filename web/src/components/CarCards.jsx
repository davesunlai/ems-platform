// 🚘 Karta vozu (sdílená: stránka Auta + záložka v panelu wallboxu)
const age = (iso) => { if (!iso) return "—"; const s = Math.round((Date.now() - new Date(iso)) / 1000);
  return s < 90 ? `před ${s} s` : s < 5400 ? `před ${Math.round(s / 60)} min` : s < 172800 ? `před ${Math.round(s / 3600)} h` : `před ${Math.round(s / 86400)} dny`; };

export function CarCard({ car, stats, monthLabel }) {
  const soc = car.soc != null ? Number(car.soc) : null;
  const col = soc == null ? "var(--muted)" : soc < 20 ? "#f85149" : soc < 50 ? "var(--amber)" : "var(--green)";
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 10, padding: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 22, position: "relative", display: "inline-block" }}>🚘
          {car.plugged_bool && (
            <svg viewBox="0 0 20 20" width="18" height="18" style={{ position: "absolute", left: -8, bottom: -4, animation: car.charging ? "plugblink 0.7s ease-in-out infinite" : "none" }} title="kabel zapojen">
              <style>{`@keyframes plugblink{0%,100%{opacity:1}50%{opacity:.2}}`}</style>
              <path d="M3,20 C3,14 7,13 8,9" fill="none" stroke="#3fb950" strokeWidth="1.8" strokeLinecap="round" />
              <rect x="5" y="4" width="7" height="6" rx="1.5" fill="#3fb950" /><rect x="12" y="5" width="4" height="1.4" fill="#3fb950" /><rect x="12" y="7.6" width="4" height="1.4" fill="#3fb950" />
              {!car.charging && <g><circle cx="15" cy="3.5" r="3.5" fill="#d29922" /><rect x="13.4" y="1.7" width="1.1" height="3.6" fill="#0d1117" /><rect x="15.5" y="1.7" width="1.1" height="3.6" fill="#0d1117" /></g>}
            </svg>)}
        </span>
        <div><b>{car.name}</b>{car.model && car.model !== car.name ? <span className="muted" style={{ fontSize: 12 }}> · {car.model}</span> : null}
          <div className="muted" style={{ fontSize: 11 }}>{car.vin} · {age(car.updated_at)}</div>
          {stats && (
            <div style={{ fontSize: 12, marginTop: 3 }} title={`nabito na wallboxu ${stats.kwh_wallbox} kWh, jinde ≈ ${stats.kwh_away} kWh`}>
              📆 {monthLabel}: nabito <b>{stats.kwh} kWh</b>{stats.kwh_away > 0 ? <span className="muted"> (doma {stats.kwh_wallbox} · jinde ≈ {stats.kwh_away})</span> : null}
              {" · "}ujeto <b>{stats.km != null ? `${Math.round(stats.km).toLocaleString("cs-CZ")} km` : "—"}</b>
              {stats.kwh_per_100km != null && <> · <b>{stats.kwh_per_100km} kWh/100 km</b></>}
            </div>)}
        </div>
        <div style={{ marginLeft: "auto", textAlign: "right" }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: col }}>{soc != null ? `${Math.round(soc)} %` : "—"}</div>
          {car.range_km != null && <div className="muted" style={{ fontSize: 12 }}>{Math.round(Number(car.range_km))} km</div>}
        </div>
      </div>
      {soc != null && <div style={{ height: 6, background: "var(--border)", borderRadius: 3, margin: "8px 0" }}>
        <div style={{ width: `${Math.max(0, Math.min(100, soc))}%`, height: 6, background: col, borderRadius: 3 }} />
        {car.target_soc != null && <div style={{ position: "relative", top: -8, left: `${Math.min(100, Number(car.target_soc))}%`, width: 2, height: 10, background: "var(--fg)" }} title={`cíl ${car.target_soc} %`} />}
      </div>}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 12.5 }}>
        <span>{car.charging ? "⚡ nabíjí" : car.plugged_bool ? "⏸ zapojeno · nenabíjí" : car.plugged_bool === false ? "odpojeno" : "—"}{car.charging && car.charging_power_kw != null ? ` ${Number(car.charging_power_kw).toFixed(1)} kW` : ""}</span>
        {car.target_soc != null && <span>cíl <b>{Math.round(Number(car.target_soc))} %</b></span>}
        {car.kwh_to_target != null && <span>do cíle <b>{car.kwh_to_target} kWh</b></span>}
        {car.kwh_now != null && <span>nabito <b>{Number(car.kwh_now).toFixed(0)}{car.capacity_kwh != null ? ` / ${Number(car.capacity_kwh).toFixed(0)}` : ""} kWh</b></span>}
        {car.odometer_km != null && <span>ujeto dnes / celkem <b>{car.km_today != null ? Math.round(Number(car.km_today)) : "–"} / {Math.round(Number(car.odometer_km)).toLocaleString("cs-CZ")} km</b></span>}
        {car.lat != null && car.lon != null && <a className="muted" href={`https://maps.google.com/?q=${car.lat},${car.lon}`} target="_blank" rel="noreferrer">📍 poloha</a>}
      </div>
      {!car.keys_received && <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>Zatím žádná data — čeká se na stream / REST.</div>}
    </div>
  );
}
