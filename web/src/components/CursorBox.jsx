// Jednotný box u křížového kurzoru (stejné pravidlo jako graf testu baterie):
// box stojí ~48 px VEDLE kurzoru (vpravo; u pravého okraje vlevo), svisle u kurzoru a vždy uvnitř kontejneru — nikdy pod kurzorem.
// Používá souřadnice kurzoru v px vůči kontejneru s position: relative (cursorPos z onMouseMove).
export const GAP = 48;

export function cursorPos(e, offsetY = 0) {
  const r = e.currentTarget.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top + offsetY, w: r.width, h: r.height + offsetY };
}

export const CURSOR_LINE = { stroke: "var(--fg)", strokeWidth: 0.8, strokeDasharray: "3 3", opacity: 0.7 };

export default function CursorBox({ pos, width = 250, height = 120, children, style }) {
  if (!pos) return null;
  const W = pos.w || 1200, H = pos.h || 300;
  const left = pos.x + GAP + width < W ? pos.x + GAP : Math.max(0, pos.x - GAP - width);
  const top = Math.max(0, Math.min(pos.y - 40, Math.max(0, H - height)));
  return (
    <div style={{ position: "absolute", left, top, minWidth: width, background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 8,
                  padding: "6px 10px", fontSize: 12.5, whiteSpace: "nowrap", pointerEvents: "none", zIndex: 5, boxShadow: "0 4px 14px rgba(0,0,0,.4)", ...style }}>
      {children}
    </div>
  );
}
