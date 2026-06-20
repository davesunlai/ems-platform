// Kompaktní sada SVG ikon (stroke = currentColor), použitá u veličin i ovládání.
const P = {
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" /></>,
  bolt: <path d="M13 2 4 14h7l-1 8 9-12h-7z" fill="currentColor" stroke="none" />,
  battery: <><rect x="2" y="7" width="17" height="10" rx="2" /><path d="M22 11v2" /></>,
  thermo: <path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z" />,
  plug: <><path d="M9 2v6M15 2v6M6 8h12v2a6 6 0 0 1-12 0z" /><path d="M12 16v6" /></>,
  gauge: <><path d="M3.5 18a9 9 0 1 1 17 0" /><path d="M12 14l3.5-3.5" /></>,
  wave: <path d="M2 12c2.5-5 4.5-5 7 0s4.5 5 7 0 4.5-5 6 0" />,
  heart: <path d="M20.8 5.6a5 5 0 0 0-7.8-1L12 5.5l-1-1a5 5 0 0 0-7.8 6.3L12 20l8.8-9.2a5 5 0 0 0 0-5.2z" />,
  calendar: <><rect x="3" y="4" width="18" height="17" rx="2" /><path d="M3 10h18M8 2v4M16 2v4" /></>,
  chart: <><path d="M4 20V11M10 20V5M16 20v-7M22 20H2" /></>,
  home: <><path d="M3 11l9-7 9 7" /><path d="M5 10v10h14V10" /></>,
  sliders: <><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6" /></>,
  power: <><path d="M12 2v8" /><path d="M5.6 6.6a8 8 0 1 0 12.8 0" /></>,
  dot: <circle cx="12" cy="12" r="3" />,
};

export default function Icon({ name, size = 16, style }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
         style={{ flex: "0 0 auto", ...style }} aria-hidden="true">
      {P[name] || P.dot}
    </svg>
  );
}
