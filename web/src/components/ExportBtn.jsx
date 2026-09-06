// Ikonka ⬇ v pravém horním rohu grafu — export aktuálního zobrazení do Excelu.
export default function ExportBtn({ onClick, style }) {
  return (
    <button onClick={onClick} title="Stáhnout zobrazená data do Excelu (.xlsx)"
            style={{ position: "absolute", top: 4, right: 4, zIndex: 3, cursor: "pointer",
                     background: "rgba(13,17,23,.75)", border: "1px solid var(--border)",
                     borderRadius: 6, color: "var(--muted)", padding: "2px 7px",
                     fontSize: 13, lineHeight: 1.4, ...style }}>⬇</button>
  );
}
