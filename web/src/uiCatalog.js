// Katalog prvků UI pro viditelnost per role. Klíč "page:*" = celá položka menu/stránka,
// ostatní = panely („boxy") uvnitř stránky. Přidání panelu = jeden řádek zde + vis("klíč") v JSX.
export const UI_CATALOG = [
  { page: "page:dashboard", label: "Dashboard", path: "/", items: [
    { key: "dash:stats", label: "Souhrnné karty (spotřeba, FVE, baterie, síť, TČ)" },
    { key: "dash:flow", label: "⚡ Schéma energetického toku" },
    { key: "dash:banners", label: "Pruhy vynuceného řízení" },
    { key: "dash:chart", label: "Graf výkonů" },
    { key: "dash:forecast", label: "🔮 Graf predikce" },
    { key: "dash:temp", label: "🌡️ Graf teplot" },
    { key: "dash:devices", label: "Panely zařízení (metriky)" },
    { key: "dash:billing", label: "💰 Tabulka nákladů" },
  ]},
  { page: "page:control", label: "Řízení", path: "/control", items: [
    { key: "ctl:help", label: "Nápověda" },
    { key: "ctl:summary", label: "Souhrn lokality" },
    { key: "ctl:planner", label: "🧠 Chytré řízení + ⏰ Časový plán (karta plánovače)" },
    { key: "ctl:schedule", label: "⏰ Časový plán (uvnitř karty)" },
    { key: "ctl:inverter", label: "Ruční řízení střídače (force / stop)" },
    { key: "ctl:sources", label: "Zdroje řízení modulu (🧠/⏰/⚡) + samoléčba" },
    { key: "ctl:outputs", label: "🔌 Spotřebiče / spínané výstupy" },
    { key: "ctl:audit", label: "📜 Audit povelů" },
  ]},
  { page: "page:heatpump", label: "🌀 TČ", path: "/heatpump", items: [] },
  { page: "page:emsboxes", label: "📦 EMSBOXy", path: "/emsboxes", items: [
    { key: "box:actions", label: "Servisní akce (update / reset / konzole)" },
    { key: "box:psk", label: "Wi-Fi heslo boxu" },
  ]},
  { page: "page:automation", label: "SPOT (pravidla)", path: "/automation", items: [] },
  { page: "page:ewelink", label: "eWeLink", path: "/ewelink", items: [] },
  { page: "page:localities", label: "Lokality", path: "/localities", items: [] },
  { page: "page:modules", label: "Moduly", path: "/modules", items: [] },
  { page: "page:users", label: "Uživatelé", path: "/users", items: [] },
  { page: "page:vzhled", label: "Vzhled", path: "/vzhled", items: [] },
];
export const PAGE_BY_PATH = Object.fromEntries(UI_CATALOG.map((g) => [g.path, g.page]));
