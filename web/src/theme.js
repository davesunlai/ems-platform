// Motivy vzhledu (témata) — přepínají CSS proměnné na :root.
// Uloženo u uživatele (theme + theme_custom); localStorage drží poslední pro okamžité použití.

export const THEME_VARS = ["--bg", "--bg-2", "--panel", "--panel-2", "--border", "--fg", "--muted", "--green", "--blue", "--amber"];

export const VAR_LABELS = {
  "--bg": "Pozadí", "--panel": "Panely", "--border": "Okraje",
  "--fg": "Text", "--muted": "Tlumený text", "--green": "Akcent (zelená)",
  "--blue": "Akcent (modrá)", "--amber": "Akcent (jantar)",
};

export const PRESETS = {
  midnight: {
    name: "Půlnoc (výchozí)",
    vars: { "--bg": "#0b0e13", "--bg-2": "#0f141b", "--panel": "#151b24", "--panel-2": "#1b222c",
      "--border": "#232c38", "--fg": "#e6edf3", "--muted": "#7d8da3",
      "--green": "#3fb950", "--blue": "#58a6ff", "--amber": "#d29922" },
  },
  slate: {
    name: "Břidlice",
    vars: { "--bg": "#11151c", "--bg-2": "#161b24", "--panel": "#1c232e", "--panel-2": "#232c38",
      "--border": "#303b4a", "--fg": "#e8eef5", "--muted": "#8a99ad",
      "--green": "#4cc35d", "--blue": "#6cb0ff", "--amber": "#e0a72a" },
  },
  carbon: {
    name: "Karbon",
    vars: { "--bg": "#0a0a0b", "--bg-2": "#101012", "--panel": "#161619", "--panel-2": "#1d1d22",
      "--border": "#2a2a31", "--fg": "#ededf0", "--muted": "#8b8b96",
      "--green": "#46c95a", "--blue": "#6aa8ff", "--amber": "#e0a72a" },
  },
  ocean: {
    name: "Oceán",
    vars: { "--bg": "#091016", "--bg-2": "#0d1620", "--panel": "#11202c", "--panel-2": "#162a38",
      "--border": "#1e3647", "--fg": "#e4f1f7", "--muted": "#7fa0b3",
      "--green": "#2dd4bf", "--blue": "#38bdf8", "--amber": "#fbbf24" },
  },
  light: {
    name: "Světlý",
    vars: { "--bg": "#f4f6fa", "--bg-2": "#eaeef4", "--panel": "#ffffff", "--panel-2": "#f2f5f9",
      "--border": "#d4dbe5", "--fg": "#1b2230", "--muted": "#5b6776",
      "--green": "#1a9c34", "--blue": "#1f6feb", "--amber": "#b07b0a" },
  },
};

export function resolveVars(theme, custom, saved) {
  if (theme === "custom") return { ...PRESETS.midnight.vars, ...(custom || {}) };
  if (theme && theme.startsWith("saved:")) {
    const name = theme.slice(6);
    const it = (saved || []).find((s) => s.name === name);
    if (it) return { ...PRESETS.midnight.vars, ...it.vars };
    return PRESETS.midnight.vars;
  }
  return (PRESETS[theme] || PRESETS.midnight).vars;
}

export function applyTheme(theme, custom, saved) {
  const vars = resolveVars(theme, custom, saved);
  const root = document.documentElement;
  for (const k of THEME_VARS) if (vars[k]) root.style.setProperty(k, vars[k]);
  try { localStorage.setItem("tera_theme", JSON.stringify({ theme, custom: custom || null, saved: saved || [] })); } catch { /* ignore */ }
}

export function applyInitial() {
  try {
    const raw = localStorage.getItem("tera_theme");
    if (raw) { const { theme, custom, saved } = JSON.parse(raw); applyTheme(theme, custom, saved); }
  } catch { /* ignore */ }
}
