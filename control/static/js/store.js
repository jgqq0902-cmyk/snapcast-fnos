const savedPageSize = Number(localStorage.getItem("snaproomPageSize"));

export const state = {
  system: { hostname: "本机网关", healthy: false },
  auth: { enabled: true, configured: false, authenticated: false },
  player: { state: "stop", song: {}, capabilities: {} },
  sources: [],
  zones: [],
  selectedZoneId: localStorage.getItem("snaproomZone") || "",
  queue: [],
  playlists: [],
  library: { items: [], total: 0 },
  libraryConfig: { path: "music", directories: [] },
  musicView: "albums",
  folder: "",
  query: "",
  page: 0,
  pageSize: [10, 20, 50, 100].includes(savedPageSize) ? savedPageSize : 10,
  playlistName: "",
  lyrics: null,
  artUri: "",
};

export function selectedZone() {
  return state.zones.find(zone => zone.id === state.selectedZoneId) || state.zones[0] || null;
}

export function selectZone(id) {
  state.selectedZoneId = id;
  localStorage.setItem("snaproomZone", id);
}
