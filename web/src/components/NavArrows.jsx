// Šipky ◀ ▶ pro posun okna grafu o daný úsek (stejné u všech grafů). offset = kolik úseků zpět (0 = teď).
export default function NavArrows({ offset, onStep, label, size = 13 }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <button type="button" className="btn" style={{ padding: "2px 10px", fontSize: size, lineHeight: 1 }} onClick={() => onStep(1)} title="o úsek zpět">◀</button>
      <button type="button" className="btn" style={{ padding: "2px 10px", fontSize: size, lineHeight: 1 }} onClick={() => onStep(-1)} disabled={!offset} title="o úsek vpřed">▶</button>
      {label && <span className="muted" style={{ fontSize: 11.5, marginLeft: 4 }}>{label}</span>}
    </span>
  );
}

export function rangeLabel(minutes, offsetMin) {
  const end = new Date(Date.now() - offsetMin * 60000);
  const start = new Date(Date.now() - (offsetMin + minutes) * 60000);
  const dd = (x) => x.toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" });
  const tt = (x) => x.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
  return start.toDateString() === end.toDateString() ? `${dd(start)} ${tt(start)}–${tt(end)}` : `${dd(start)} ${tt(start)} – ${dd(end)} ${tt(end)}`;
}
