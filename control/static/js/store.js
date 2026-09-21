export const state = {
  system: { hostname: "本机网关", healthy: false },
  auth: { enabled: true, configured: false, authenticated: false },
  player: { state: "stop", song: {}, capabilities: {} },
  sources: [],
  zones: [],
  selectedZoneId: localStorage.getItem("snaproomZone") || "",
};

export function selectedZone() {
  return state.zones.find(zone => zone.id === state.selectedZoneId) || state.zones[0] || null;
}

export function selectZone(id) {
  state.selectedZoneId = id;
  localStorage.setItem("snaproomZone", id);
}
