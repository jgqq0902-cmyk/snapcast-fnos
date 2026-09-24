const API_URL = "/api/player/rpc";
const EVENTS_URL = "/api/player/events";
const fields = ["Title", "Artist", "Album", "AlbumArtist", "Duration", "Track", "Name", "Pos"];
let requestId = 1000;
const radioNames = new Map();

export class MyMpdError extends Error {
  constructor(message, payload = null) { super(message); this.payload = payload; }
}

export async function call(method, params = {}) {
  const response = await fetch(API_URL, {
    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: ++requestId, method, params }),
  });
  if (response.status === 401) document.dispatchEvent(new CustomEvent("auth-required"));
  if (!response.ok) throw new MyMpdError(`播放器接口返回 HTTP ${response.status}`);
  const payload = await response.json();
  if (payload.error) throw new MyMpdError(payload.error.message || "播放器操作失败", payload.error);
  return payload.result || {};
}

export function connectNotifications(onUpdate, onState) {
  const events = new EventSource(EVENTS_URL, { withCredentials: true });
  const receive = event => { try { onUpdate?.(JSON.parse(event.data)); } catch { onUpdate?.({}); } };
  events.onopen = () => onState?.(true);
  events.addEventListener("update", receive);
  events.onerror = () => onState?.(false);
  return () => events.close();
}

export async function getPlayer() {
  const [status, song] = await Promise.all([
    call("MYMPD_API_PLAYER_STATE"),
    call("MYMPD_API_PLAYER_CURRENT_SONG").catch(() => ({})),
  ]);
  let player = normalizePlayer(status, song);
  if (isWebUri(player.song.uri) && !radioNames.has(normalizeUri(player.song.uri))) {
    await loadRadioNames().catch(() => {});
    player = normalizePlayer(status, song);
  }
  return player;
}

export function normalizePlayer(status = {}, song = {}) {
  const uri = song.uri || song.Uri || "";
  return {
    state: status.state || "stop", volume: Number(status.volume ?? 0), elapsed: Number(status.elapsedTime ?? status.elapsed ?? 0),
    duration: Number(status.totalTime ?? song.Duration ?? song.duration ?? 0), currentSongId: Number(status.currentSongId ?? song.id ?? -1),
    random: Boolean(status.random), repeat: Boolean(status.repeat),
    song: { uri, title: radioNames.get(normalizeUri(uri)) || readableTitle(song, uri), artist: song.Artist || song.AlbumArtist || "", album: song.Album || "" },
    cover: uri ? `/api/player/art?size=large&uri=${encodeURIComponent(uri)}` : "/art/album-placeholder.svg",
  };
}

export async function albums(search = "") {
  const result = await call("MYMPD_API_DATABASE_ALBUM_LIST", { offset: 0, limit: 100, expression: search ? `((any contains '${escapeMpd(search)}'))` : "", sort: "Album", sortdesc: false, fields: ["Album", "AlbumArtist"] });
  return result.data || [];
}

export async function tracks(search) {
  const result = await call("MYMPD_API_DATABASE_SEARCH", { offset: 0, limit: 100, expression: `((any contains '${escapeMpd(search)}'))`, sort: "Title", sortdesc: false, fields });
  return result.data || [];
}

export async function albumTracks(albumId) {
  const result = await call("MYMPD_API_DATABASE_ALBUM_DETAIL", { albumid: albumId, fields });
  return result.data || [];
}

export async function queue() {
  const result = await call("MYMPD_API_QUEUE_SEARCH", { offset: 0, limit: 1000, expression: "", sort: "Priority", sortdesc: false, fields });
  return result.data || [];
}

export async function playlists() {
  const result = await call("MYMPD_API_PLAYLIST_LIST", { offset: 0, limit: 500, searchstr: "", type: 0, sort: "Name", sortdesc: false, fields: ["Name", "Last-Modified"] });
  return result.data || [];
}

export async function playlistTracks(plist) {
  const result = await call("MYMPD_API_PLAYLIST_CONTENT_LIST", { plist, offset: 0, limit: 1000, expression: "", fields });
  return result.data || [];
}

export async function radios(search = "") {
  const expression = search ? `((Name contains '${escapeMpd(search)}'))` : "";
  const result = await call("MYMPD_API_WEBRADIO_FAVORITE_SEARCH", { offset: 0, limit: 1000, expression, sort: "Name", sortdesc: false });
  const data = result.data || [];
  rememberRadioNames(data);
  return data;
}

export const actions = {
  play: () => call("MYMPD_API_PLAYER_PLAY"), pause: () => call("MYMPD_API_PLAYER_PAUSE"), stop: () => call("MYMPD_API_PLAYER_STOP"),
  next: () => call("MYMPD_API_PLAYER_NEXT"), prev: () => call("MYMPD_API_PLAYER_PREV"),
  seek: seconds => call("MYMPD_API_PLAYER_SEEK_CURRENT", { seek: Math.round(seconds), relative: false }),
  volume: volume => call("MYMPD_API_PLAYER_VOLUME_SET", { volume: Math.round(volume) }),
  playSong: songId => call("MYMPD_API_PLAYER_PLAY_SONG", { songId: Number(songId) }),
  replaceUris: uris => call("MYMPD_API_QUEUE_REPLACE_URIS", { uris, play: true }),
  appendUris: uris => call("MYMPD_API_QUEUE_APPEND_URIS", { uris, play: false }),
  replacePlaylist: plist => call("MYMPD_API_QUEUE_REPLACE_PLAYLISTS", { plists: [plist], play: true }),
  removeQueue: ids => call("MYMPD_API_QUEUE_RM_IDS", { songIds: ids.map(Number) }),
  clearQueue: () => call("MYMPD_API_QUEUE_CLEAR"),
  addRandomQueue: () => call("MYMPD_API_QUEUE_ADD_RANDOM", { plist: "Database", quantity: 50, mode: 1, play: true }),
  appendPlaylistUris: (plist, uris) => call("MYMPD_API_PLAYLIST_CONTENT_APPEND_URIS", { plist, uris }),
  renamePlaylist: (plist, newName) => call("MYMPD_API_PLAYLIST_RENAME", { plist, newName }),
  removePlaylists: plists => call("MYMPD_API_PLAYLIST_RM", { plists }),
  removePlaylistPositions: (plist, positions) => call("MYMPD_API_PLAYLIST_CONTENT_RM_POSITIONS", { plist, positions: positions.map(Number).sort((a, b) => b - a) }),
  movePlaylistPosition: (plist, from, to) => call("MYMPD_API_PLAYLIST_CONTENT_MOVE_POSITION", { plist, from: Number(from), to: Number(to) }),
};

export function radioPlaylistUri(uri) { return `mympd://webradio/${encodeURI(uri).replace(/[!'()*#?;:,@&=+$~]/g, char => `%${char.charCodeAt(0).toString(16)}`)}`; }
export function coverFor(item, radio = false) {
  if (radio) return item.Image ? rewriteAsset(item.Image) : "/art/radio-placeholder.svg";
  const uri = item.FirstSongUri || item.uri || item.Uri || "";
  return uri ? `/api/player/art?size=small&uri=${encodeURIComponent(uri)}` : "/art/album-placeholder.svg";
}
export function rewriteAsset(uri) { return uri?.startsWith("/albumart") ? `/api/player/art?source=${encodeURIComponent(uri)}` : "/art/radio-placeholder.svg"; }
function escapeMpd(value) { return String(value).replaceAll("\\", "\\\\").replaceAll("'", "\\'"); }
function fileName(uri) { return decodeURIComponent(String(uri).split("/").pop() || "").replace(/\.[^.]+$/, ""); }
function isWebUri(value) { return /^https?:\/\//i.test(String(value || "")); }
function normalizeUri(value) { return String(value || "").trim().replace(/\/$/, ""); }
function readableTitle(song, uri) {
  const title = song.Title || song.Name || "";
  return (title && !isWebUri(title) ? title : fileName(uri)) || "等待播放";
}
function rememberRadioNames(items) {
  items.forEach(item => {
    if (item?.StreamUri && item?.Name) radioNames.set(normalizeUri(item.StreamUri), item.Name);
  });
}
async function loadRadioNames() {
  const result = await call("MYMPD_API_WEBRADIO_FAVORITE_SEARCH", { offset: 0, limit: 1000, expression: "", sort: "Name", sortdesc: false });
  rememberRadioNames(result.data || []);
}
