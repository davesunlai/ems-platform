// Tenký API klient: připojí Bearer token, řeší 401.
const TOKEN_KEY = "ems_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

async function request(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { clearToken(); onUnauthorized(); throw new Error("Neautorizováno"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  login: (username, password) => request("/api/auth/login", { method: "POST", body: { username, password } }),
  me: () => request("/api/auth/me"),
  setTheme: (theme, custom, saved) => request("/api/auth/me/theme", { method: "PUT", body: { theme, custom, saved } }),
  changePassword: (old_password, new_password) => request("/api/auth/change-password", { method: "POST", body: { old_password, new_password } }),
  forgotPassword: (email) => request("/api/auth/forgot-password", { method: "POST", body: { email } }),
  resetPassword: (token, new_password) => request("/api/auth/reset-password", { method: "POST", body: { token, new_password } }),
  devices: () => request("/api/devices"),
  latest: (id) => request(`/api/devices/${encodeURIComponent(id)}/latest`),
  history: (id, metric, minutes = 360, offset = 0) =>
    request(`/api/devices/${encodeURIComponent(id)}/history?metric=${metric}&minutes=${minutes}&offset=${offset}`),
  aggregate: (ids, metrics, minutes = 360, offset = 0) =>
    request(`/api/devices/aggregate?ids=${encodeURIComponent(ids.join(","))}&metrics=${metrics.join(",")}&minutes=${minutes}&offset=${offset}`),
  aggregateNow: (ids, loc) => request(`/api/devices/aggregate-now?ids=${encodeURIComponent(ids.join(","))}${loc != null ? `&loc=${loc}` : ""}`),
  listUsers: () => request("/api/admin/users"),
  createUser: (u) => request("/api/admin/users", { method: "POST", body: u }),
  updateUser: (id, patch) => request(`/api/admin/users/${encodeURIComponent(id)}`, { method: "PATCH", body: patch }),
  deleteUser: (id) => request(`/api/admin/users/${encodeURIComponent(id)}`, { method: "DELETE" }),
  sendReset: (id) => request(`/api/admin/users/${encodeURIComponent(id)}/send-reset`, { method: "POST" }),
  listModules: () => request("/api/admin/modules"),
  createModule: (m) => request("/api/admin/modules", { method: "POST", body: m }),
  updateModule: (id, patch) => request(`/api/admin/modules/${encodeURIComponent(id)}`, { method: "PATCH", body: patch }),
  deleteModule: (id) => request(`/api/admin/modules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  controlModules: () => request("/api/control/modules"),
  enqueueCommand: (id, action, params = {}) =>
    request(`/api/control/${encodeURIComponent(id)}/command`, { method: "POST", body: { action, params } }),
  commandStatus: (cmdId) => request(`/api/control/command/${cmdId}`),
  listOutputs: () => request("/api/outputs"),
  createOutput: (o) => request("/api/outputs", { method: "POST", body: o }),
  updateOutput: (id, patch) => request(`/api/outputs/${id}`, { method: "PUT", body: patch }),
  deleteOutput: (id) => request(`/api/outputs/${id}`, { method: "DELETE" }),
  testOutput: (id, on) => request(`/api/outputs/${id}/test`, { method: "POST", body: { on } }),
  getMode: (id) => request(`/api/control/${encodeURIComponent(id)}/mode`),
  setBatteryMode: (id, body) => request(`/api/control/${encodeURIComponent(id)}/battery-mode`, { method: "POST", body }),
  controlAudit: () => request("/api/control/audit"),
  controlStates: (ids) => request(`/api/control/states?ids=${encodeURIComponent(ids)}`),
  getPlanner: (id) => request(`/api/planner/${id}`),
  setPlannerConfig: (id, cfg) => request(`/api/planner/${id}/config`, { method: "PUT", body: cfg }),
  refreshPlanner: (id) => request(`/api/planner/${id}/refresh`, { method: "POST" }),
  plannerControlled: () => request(`/api/planner/controlled/devices`),
  contactList: () => request("/api/contact"),
  setContact: (id, s) => request(`/api/contact/${encodeURIComponent(id)}`, { method: "PUT", body: s }),
  contactSwitch: (id, on) => request(`/api/contact/${encodeURIComponent(id)}/switch?on=${on}`, { method: "POST" }),
  ewelinkDevices: () => request("/api/ewelink/devices"),
  ewelinkAuthUrl: () => request("/api/ewelink/auth-url"),
  ewelinkSwitch: (deviceid, on) => request("/api/ewelink/switch", { method: "POST", body: { deviceid, on } }),
  spot: () => request("/api/market/spot"),
  spotCurve: (days = 1) => request(`/api/market/spot-curve?days=${days}`),
  setManualPrice: (price) => request("/api/admin/market/manual", { method: "POST", body: { price } }),
  clearManualPrice: () => request("/api/admin/market/manual", { method: "DELETE" }),
  listRules: () => request("/api/automation"),
  createRule: (r) => request("/api/admin/automation", { method: "POST", body: r }),
  updateRule: (id, patch) => request(`/api/admin/automation/${encodeURIComponent(id)}`, { method: "PATCH", body: patch }),
  deleteRule: (id) => request(`/api/admin/automation/${encodeURIComponent(id)}`, { method: "DELETE" }),
  listLocalities: () => request("/api/admin/localities"),
  localityBilling: (id) => request(`/api/localities/${id}/billing`),
  localityOutages: (id) => request(`/api/localities/${id}/outages`),
  alerts: () => request("/api/alerts"),
  refreshOutages: (id) => request(`/api/admin/localities/${id}/outages/refresh`, { method: "POST" }),
  setBilling: (id, settings) => request(`/api/admin/localities/${id}/billing`, { method: "PUT", body: settings }),
  createLocality: (l) => request("/api/admin/localities", { method: "POST", body: l }),
  updateLocality: (id, patch) => request(`/api/admin/localities/${id}`, { method: "PATCH", body: patch }),
  geocode: (q) => request(`/api/forecast/geocode?q=${encodeURIComponent(q)}`),
  forecastBlocks: (id) => request(`/api/forecast/${id}/blocks`),
  setForecastBlocks: (id, blocks) => request(`/api/forecast/${id}/blocks`, { method: "PUT", body: { blocks } }),
  forecastData: (id) => request(`/api/forecast/${id}`),
  refreshForecast: (id) => request(`/api/forecast/${id}/refresh`, { method: "POST" }),
  getTariff: (id) => request(`/api/pricing/${id}/tariff`),
  addTariff: (id, t) => request(`/api/pricing/${id}/tariff`, { method: "POST", body: t }),
  deleteTariff: (vid) => request(`/api/pricing/tariff/${vid}`, { method: "DELETE" }),
  deleteLocality: (id) => request(`/api/admin/localities/${id}`, { method: "DELETE" }),
  assignUser: (id, user_id) => request(`/api/admin/localities/${id}/users`, { method: "POST", body: { user_id } }),
  unassignUser: (id, user_id) => request(`/api/admin/localities/${id}/users/${user_id}`, { method: "DELETE" }),
  setUserNotify: (id, user_id, notify) => request(`/api/admin/localities/${id}/users/${user_id}/notify`, { method: "PUT", body: { notify } }),
  assignDevice: (id, module_id) => request(`/api/admin/localities/${id}/devices`, { method: "POST", body: { module_id } }),
  unassignDevice: (id, module_id) => request(`/api/admin/localities/${id}/devices/${encodeURIComponent(module_id)}`, { method: "DELETE" }),
};
