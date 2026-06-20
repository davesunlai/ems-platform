// Sdílené definice veličin — používá je editace modulu i dashboard.

export const MAX_TRACKED = 20;

export const METRIC_LABEL = {
  pv_power: "FVE výkon", load_power: "Spotřeba", grid_power: "Síť",
  battery_power: "Baterie výkon (Σ)", battery_soc: "Baterie SoC (Ø)",
  battery_soc_1: "Baterie 1 SoC", battery_soc_2: "Baterie 2 SoC",
  battery_voltage_1: "Baterie 1 napětí", battery_voltage_2: "Baterie 2 napětí",
  battery_current_1: "Baterie 1 proud", battery_current_2: "Baterie 2 proud",
  battery_power_1: "Baterie 1 výkon", battery_power_2: "Baterie 2 výkon",
  battery_soh_1: "Baterie 1 SOH", battery_soh_2: "Baterie 2 SOH",
  battery_temp_1: "Baterie 1 teplota", battery_temp_2: "Baterie 2 teplota",
  energy_today: "FVE dnes", energy_pv_total: "FVE celkem",
  energy_import: "Import celkem", energy_export: "Export celkem",
  grid_voltage_l1: "Síť napětí L1", grid_voltage_l2: "Síť napětí L2", grid_voltage_l3: "Síť napětí L3",
  active_power: "Činný výkon", reactive_power: "Jalový výkon",
  voltage: "Napětí", current: "Proud", frequency: "Frekvence", temperature: "Teplota měniče",
};

// název SVG ikony (viz components/Icon.jsx) podle veličiny
export function iconFor(k) {
  if (k === "energy_today") return "calendar";
  if (k === "grid_power") return "plug";
  if (k === "load_power") return "home";
  if (k === "pv_power") return "sun";
  if (k === "frequency") return "wave";
  if (k.startsWith("energy_")) return "chart";
  if (k === "temperature" || k.includes("temp")) return "thermo";
  if (k.includes("soh")) return "heart";
  if (k.includes("soc")) return "battery";
  if (k.includes("voltage")) return "gauge";
  if (k.includes("current")) return "wave";
  if (k.includes("power")) return "bolt";
  return "dot";
}

// Skupiny veličin (pořadí = pořadí zobrazení); každá má ikonu a seznam metrik.
export const METRIC_GROUPS = [
  { id: "fve", label: "FVE", icon: "sun", metrics: ["pv_power", "energy_today", "energy_pv_total", "energy_import", "energy_export"] },
  { id: "grid", label: "Síť", icon: "plug", metrics: ["grid_power", "grid_voltage_l1", "grid_voltage_l2", "grid_voltage_l3"] },
  { id: "inverter", label: "Měnič", icon: "sliders", metrics: ["active_power", "reactive_power", "frequency", "temperature", "load_power", "voltage", "current"] },
  { id: "battery", label: "Baterie — souhrn", icon: "battery", metrics: ["battery_soc", "battery_power"] },
  { id: "bat1", label: "Baterie 1", icon: "battery", metrics: ["battery_soc_1", "battery_voltage_1", "battery_current_1", "battery_power_1", "battery_soh_1", "battery_temp_1"] },
  { id: "bat2", label: "Baterie 2", icon: "battery", metrics: ["battery_soc_2", "battery_voltage_2", "battery_current_2", "battery_power_2", "battery_soh_2", "battery_temp_2"] },
];

const _GROUP_OF = {};
METRIC_GROUPS.forEach((g) => g.metrics.forEach((m) => { _GROUP_OF[m] = g.id; }));
export const groupOf = (k) => _GROUP_OF[k] || "other";

// Rozdělí seznam přítomných metrik do skupin (zachová pořadí skupin i metrik).
export function groupMetrics(keys) {
  const present = new Set(keys);
  const out = METRIC_GROUPS
    .map((g) => ({ ...g, items: g.metrics.filter((m) => present.has(m)) }))
    .filter((g) => g.items.length);
  const known = new Set(METRIC_GROUPS.flatMap((g) => g.metrics));
  const other = keys.filter((k) => !known.has(k));
  if (other.length) out.push({ id: "other", label: "Ostatní", icon: "dot", items: other });
  return out;
}

// Kompletní katalog MĚŘENÝCH veličin podle adaptéru a typu.
export const METRIC_CATALOG = {
  "solis:hybrid": ["pv_power", "grid_power", "energy_pv_total", "energy_today", "temperature",
    "grid_voltage_l1", "grid_voltage_l2", "grid_voltage_l3",
    "battery_soc", "battery_power",
    "battery_soc_1", "battery_voltage_1", "battery_current_1", "battery_power_1", "battery_soh_1", "battery_temp_1",
    "battery_soc_2", "battery_voltage_2", "battery_current_2", "battery_power_2", "battery_soh_2", "battery_temp_2"],
  "solis:generation": ["pv_power", "grid_power", "energy_pv_total", "energy_today", "temperature",
    "grid_voltage_l1", "grid_voltage_l2", "grid_voltage_l3"],
  "solis:storage": ["battery_soc", "voltage", "current", "battery_power"],
  "solis:grid_point": ["grid_power"],
};
export const metricsFor = (adapter, dtype, live) => {
  const cat = METRIC_CATALOG[`${adapter}:${dtype}`] || [];
  return [...cat, ...live.filter((k) => !cat.includes(k))];
};

// Katalog OVLÁDÁNÍ / KONFIGURACE (zápisová vrstva — zatím fáze C, příprava).
export const CONTROL_CATALOG = {
  "solis:hybrid": [
    { key: "work_mode", label: "Pracovní režim (Self-Use / nucený)", icon: "sliders" },
    { key: "force_charge", label: "Nucené nabíjení baterie", icon: "bolt" },
    { key: "force_discharge", label: "Nucené vybíjení do sítě", icon: "bolt" },
    { key: "charge_current_limit", label: "Limit nabíjecího proudu", icon: "wave" },
    { key: "discharge_current_limit", label: "Limit vybíjecího proudu", icon: "wave" },
    { key: "soc_min", label: "Ochrana baterie — min. SOC", icon: "battery" },
    { key: "timed_windows", label: "Časová okna nabíjení/vybíjení", icon: "calendar" },
    { key: "spot_discharge", label: "Vybíjení při vysoké ceně (spot)", icon: "chart" },
  ],
};
export const controlFor = (adapter, dtype) => CONTROL_CATALOG[`${adapter}:${dtype}`] || [];
