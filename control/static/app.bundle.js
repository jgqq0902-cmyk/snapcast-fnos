(() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropSymbols = Object.getOwnPropertySymbols;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __propIsEnum = Object.prototype.propertyIsEnumerable;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __spreadValues = (a, b) => {
    for (var prop in b || (b = {}))
      if (__hasOwnProp.call(b, prop))
        __defNormalProp(a, prop, b[prop]);
    if (__getOwnPropSymbols)
      for (var prop of __getOwnPropSymbols(b)) {
        if (__propIsEnum.call(b, prop))
          __defNormalProp(a, prop, b[prop]);
      }
    return a;
  };

  // control/static/js/api.js?v=20261002-ios2
  var ApiError = class extends Error {
    constructor(message, status = 0, details = null) {
      super(message);
      this.status = status;
      this.details = details;
    }
  };
  async function request(url, options = {}) {
    const response = await fetch(url, __spreadValues({ credentials: "same-origin" }, options));
    const type = response.headers.get("content-type") || "";
    const data = type.includes("json") ? await response.json() : await response.text();
    if (response.status === 401 && url !== "/api/login") {
      document.dispatchEvent(new CustomEvent("auth-required"));
    }
    if (!response.ok || data && data.ok === false) {
      throw new ApiError(data && data.error || "HTTP ".concat(response.status), response.status, typeof data === "object" ? data : null);
    }
    return data;
  }
  function post(url, data) {
    return request(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
  }

  // control/static/js/store.js?v=20261002-ios2
  var state = {
    system: { hostname: "本机网关", healthy: false },
    auth: { enabled: true, configured: false, authenticated: false },
    sources: [],
    zones: [],
    mainGroup: null,
    selectedZoneId: localStorage.getItem("snaproomZone") || ""
  };

  // control/static/js/ui.js?v=20261002-ios2
  var $ = (selector, root = document) => root.querySelector(selector);
  var $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  var icon = (name) => '<svg aria-hidden="true"><use href="/icons.svg#icon-'.concat(name, '"/></svg>');
  var esc = (value) => String(value === null || value === void 0 ? "" : value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  function clearChildren(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }
  function installThumbDragRange(input) {
    if (!input || input.closest(".thumb-only-range")) return;
    input.dataset.thumbDrag = "ready";
    input.classList.add("thumb-drag-range");
    const shell = document.createElement("span");
    shell.className = "thumb-only-range";
    input.before(shell);
    shell.append(input);
    const handle = document.createElement("span");
    handle.className = "thumb-only-handle";
    handle.setAttribute("aria-hidden", "true");
    shell.append(handle);
    const sync = () => {
      const min = Number(input.min || 0), max = Number(input.max || 100);
      const ratio = max > min ? (Number(input.value) - min) / (max - min) : 0;
      const visualRatio = getComputedStyle(input).direction === "rtl" ? 1 - ratio : ratio;
      const fraction = Math.max(0, Math.min(1, visualRatio));
      shell.style.setProperty("--thumb-position", "calc(".concat(fraction * 100, "% + ").concat(10 - fraction * 20, "px)"));
    };
    let dragging = false, initialValue, pointerId;
    handle.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && !matchMedia("(pointer: coarse)").matches) return;
      if (dragging || input.disabled || input.closest("[inert]")) return;
      initialValue = input.value;
      pointerId = event.pointerId;
      dragging = true;
      input.dataset.dragging = "true";
      handle.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    handle.addEventListener("pointermove", (event) => {
      if (!dragging || event.pointerId !== pointerId) return;
      const rect = shell.getBoundingClientRect();
      let ratio = Math.max(0, Math.min(1, (event.clientX - rect.left - 10) / Math.max(1, rect.width - 20)));
      if (getComputedStyle(input).direction === "rtl") ratio = 1 - ratio;
      const min = Number(input.min || 0), max = Number(input.max || 100), step = Number(input.step || 1);
      const raw = min + ratio * (max - min);
      input.value = String(Math.max(min, Math.min(max, Math.round((raw - min) / step) * step + min)));
      sync();
      input.dispatchEvent(new Event("input", { bubbles: true }));
      event.preventDefault();
    });
    const finish = (event) => {
      if (!dragging || event.pointerId !== pointerId) return;
      dragging = false;
      delete input.dataset.dragging;
      if (event.type !== "pointerup" || input.disabled || input.closest("[inert]")) {
        input.value = initialValue;
        sync();
        input.dispatchEvent(new Event("input", { bubbles: true }));
      } else if (input.value !== initialValue) {
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (event && event.pointerId !== void 0 && handle.hasPointerCapture && handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    };
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
    handle.addEventListener("lostpointercapture", finish);
    input.addEventListener("input", sync);
    input.addEventListener("thumb-sync", sync);
    sync();
  }
  function syncThumbDragRange(input) {
    if (input) input.dispatchEvent(new Event("thumb-sync"));
  }
  var toastTimer;
  function toast(message, error = false, duration = 2800) {
    const node = $("#toast");
    node.textContent = message;
    node.className = "toast show".concat(error ? " error" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      node.className = "toast";
    }, duration);
  }
  function openDialog(selector) {
    const dialog = typeof selector === "string" ? $(selector) : selector;
    if (!dialog || dialog.hasAttribute("open")) return;
    dialog.setAttribute("open", "");
    dialog.setAttribute("aria-modal", "true");
  }
  function closeDialog(selector) {
    const dialog = typeof selector === "string" ? $(selector) : selector;
    if (!dialog || !dialog.hasAttribute("open")) return;
    dialog.removeAttribute("open");
    dialog.dispatchEvent(new Event("close"));
  }
  function askConfirm(title, message) {
    return new Promise((resolve) => {
      const dialog = $("#confirmDialog");
      $("#confirmTitle").textContent = title;
      $("#confirmMessage").textContent = message;
      $("#confirmForm").onsubmit = (event) => {
        event.preventDefault();
        closeDialog(dialog);
        resolve(true);
      };
      dialog.addEventListener("close", () => resolve(false), { once: true });
      openDialog(dialog);
    });
  }

  // control/static/js/zones.js?v=20261002-ios2
  var renderSignature = "";
  function renderZones(force = false) {
    const clients = state.mainGroup && state.mainGroup.clients || [];
    $("#deviceCount").textContent = clients.length;
    const signature = JSON.stringify({
      groupId: state.mainGroup && state.mainGroup.id || "",
      clients: clients.map((client) => ({
        id: client.id,
        name: client.name,
        connected: Boolean(client.connected),
        active: Boolean(client.participating !== null && client.participating !== void 0 ? client.participating : client.active !== null && client.active !== void 0 ? client.active : !client.muted),
        audible: Boolean(client.audible),
        volume: Number(client.volume),
        latency: Number(client.latency)
      }))
    });
    if (!force && signature === renderSignature) return;
    if ($("#devicePanelHost dialog[open]")) return;
    renderSignature = signature;
    const host = $("#devicePanelHost");
    clearChildren(host);
    if (!state.mainGroup) {
      host.innerHTML = '<section class="state-panel"><svg class="state-mark" aria-hidden="true"><use href="/icons.svg#icon-speaker"/></svg><h2>暂未发现设备</h2><div class="state-actions"><button class="secondary-btn" data-empty-refresh>刷新</button></div></section>';
      $("[data-empty-refresh]", host).onclick = () => document.dispatchEvent(new CustomEvent("state-refresh"));
      return;
    }
    host.append(devicesPanel(state.mainGroup));
  }
  function devicesPanel(zone) {
    const panel = document.createElement("section");
    const clients = zone.clients || [];
    panel.className = "devices-panel";
    panel.setAttribute("aria-label", "设备控制");
    panel.innerHTML = '<div class="compact-client-list"></div>';
    const list = $(".compact-client-list", panel);
    clients.forEach((client, index) => list.append(clientCard(client, index)));
    return panel;
  }
  function clientCard(client, index) {
    const active = client.participating !== null && client.participating !== void 0 ? client.participating : client.active !== null && client.active !== void 0 ? client.active : !client.muted;
    const card = document.createElement("article");
    const variant = speakerVariant(client.name, client.id, index);
    card.className = "speaker-unit".concat(client.connected ? "" : " is-offline").concat(active ? " is-active" : " is-inactive").concat(client.audible ? " is-audible" : "");
    card.innerHTML = '<button class="speaker-toggle" aria-label="'.concat(esc(client.name)).concat(active ? "关闭" : "激活", '" ').concat(client.connected ? "" : "disabled", '><span class="speaker-visual ').concat(variant, '" aria-hidden="true"><i></i><i></i><i></i></span><strong>').concat(esc(client.name), '</strong><span class="speaker-light" aria-hidden="true"></span></button>\n    <button class="speaker-settings" aria-label="打开 ').concat(esc(client.name), ' 设置">').concat(icon("settings"), '</button>\n    <div class="device-dialog modal" role="dialog" aria-modal="true" aria-label="').concat(esc(client.name), ' 设置"><form class="device-dialog-card">\n      <header><div class="speaker-mini ').concat(variant, '" aria-hidden="true"><i></i></div><div class="device-identity"><span>设备名称</span><strong class="device-name-display">').concat(esc(client.name), '</strong><label hidden><input class="device-name" maxlength="64" value="').concat(esc(client.name), '" aria-label="设备名称"></label></div><button type="button" class="edit-device-name" aria-label="编辑设备名称">').concat(icon("edit"), '</button><button type="button" class="dialog-close" aria-label="关闭">').concat(icon("close"), '</button></header>\n      <label class="device-volume-control"><span>').concat(icon("volume"), '</span><input aria-label="').concat(esc(client.name), '音量" type="range" min="0" max="100" value="').concat(client.volume, '" ').concat(client.connected && active ? "" : "disabled", "><output>").concat(client.volume, '</output></label>\n      <section class="latency-control"><div><span>向右加快 · 向左减慢</span><output>').concat(client.latency, ' ms</output></div><input class="latency-range" aria-label="').concat(esc(client.name), '延迟" type="range" min="-500" max="500" step="10" dir="rtl" value="').concat(Math.max(-500, Math.min(500, client.latency)), '"><footer><button type="button" data-step="10" aria-label="声音减慢">＋</button><button type="button" data-zero aria-label="延迟归零">').concat(icon("reset"), '</button><label><input class="latency-number" type="number" min="-1000" max="5000" step="10" value="').concat(client.latency, '"><span>ms</span></label><button type="button" data-step="-10" aria-label="声音加快">−</button></footer></section>\n      <button class="save-device-name" type="submit" hidden>保存名称</button>\n    </form></div>');
    $(".speaker-toggle", card).onclick = () => mutate("/api/snapcast/client-active", { clientId: client.id, active: !active }, true);
    const dialog = $(".device-dialog", card);
    dialog.addEventListener("close", () => renderZones(true));
    $(".speaker-settings", card).onclick = () => openDialog(dialog);
    $(".dialog-close", card).onclick = () => closeDialog(dialog);
    $(".edit-device-name", dialog).onclick = () => {
      $(".device-name-display", dialog).hidden = true;
      $(".device-identity label", dialog).hidden = false;
      $(".save-device-name", dialog).hidden = false;
      $(".edit-device-name", dialog).hidden = true;
      $(".device-name", dialog).focus();
      $(".device-name", dialog).select();
    };
    $("form", dialog).onsubmit = async (event) => {
      event.preventDefault();
      const name = $(".device-name", dialog).value.trim();
      if (name && await mutate("/api/snapcast/client-name", { clientId: client.id, name }, true)) closeDialog(dialog);
    };
    const volume = $(".device-volume-control input", card), volumeOutput = $(".device-volume-control output", card);
    volume.oninput = () => {
      volumeOutput.value = volume.value;
    };
    volume.onchange = () => mutate("/api/snapcast/volume", { clientId: client.id, percent: Number(volume.value), muted: false }, true);
    const range = $(".latency-range", card), number = $(".latency-number", card), latencyOutput = $(".latency-control>div output", card);
    const setLatency = (value) => {
      if (String(value).trim() === "" || !Number.isFinite(Number(value))) {
        toast("请输入有效的延迟数值", true);
        return;
      }
      const normalized = Math.max(-1e3, Math.min(5e3, Math.round(Number(value) / 10) * 10));
      number.value = normalized;
      range.value = Math.max(-500, Math.min(500, normalized));
      latencyOutput.value = "".concat(normalized, " ms");
      syncThumbDragRange(range);
      mutate("/api/snapcast/latency", { clientId: client.id, latency: normalized }, true);
    };
    range.oninput = () => {
      number.value = range.value;
      latencyOutput.value = "".concat(range.value, " ms");
    };
    range.onchange = () => setLatency(range.value);
    installThumbDragRange(volume);
    installThumbDragRange(range);
    number.onchange = () => setLatency(number.value);
    $$("[data-step]", card).forEach((button) => {
      button.onclick = () => setLatency(Number(number.value) + Number(button.dataset.step));
    });
    $("[data-zero]", card).onclick = () => setLatency(0);
    return card;
  }
  function speakerVariant(name, id, index) {
    const normalized = "".concat(name, " ").concat(id).toLowerCase();
    if (/s12|小爱|xiaoai/.test(normalized)) return "speaker-white-tower";
    if (/\br1\b|斐讯|phicomm/.test(normalized)) return "speaker-black-tower";
    const variants = ["speaker-mesh", "speaker-silver", "speaker-pebble", "speaker-oval"];
    const hash = [...normalized].reduce((sum, char) => sum + char.charCodeAt(0), index);
    return variants[Math.abs(hash) % variants.length];
  }
  async function mutate(url, payload, quiet = false) {
    try {
      await post(url, payload);
      document.dispatchEvent(new CustomEvent("state-refresh"));
      if (!quiet) toast("已更新");
      return true;
    } catch (error) {
      toast(error.message, true);
      document.dispatchEvent(new CustomEvent("state-refresh"));
      return false;
    }
  }

  // control/static/js/mympd-adapter.js?v=20261002-ios2
  var API_URL = "/api/player/rpc";
  var EVENTS_URL = "/api/player/events";
  var fields = ["Title", "Artist", "Album", "AlbumArtist", "Duration", "Track", "Name", "Pos"];
  var playlistFields = ["Pos", "Title", "Artist", "Album", "Duration"];
  var requestId = 1e3;
  var radioNames = /* @__PURE__ */ new Map();
  function mpdBoolean(value) {
    return value === true || value === 1 || value === "1";
  }
  var MyMpdError = class extends Error {
    constructor(message, payload = null) {
      super(message);
      this.payload = payload;
    }
  };
  async function call(method, params = {}) {
    const response = await fetch(API_URL, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: ++requestId, method, params })
    });
    if (response.status === 401) document.dispatchEvent(new CustomEvent("auth-required"));
    if (!response.ok) throw new MyMpdError("播放器接口返回 HTTP ".concat(response.status));
    const payload = await response.json();
    if (payload.error) throw new MyMpdError(payload.error.message || "播放器操作失败", payload.error);
    return payload.result || {};
  }
  function connectNotifications(onUpdate, onState) {
    const events = new EventSource(EVENTS_URL);
    const receive = (event) => {
      try {
        if (onUpdate) onUpdate(JSON.parse(event.data));
      } catch (e) {
        if (onUpdate) onUpdate({});
      }
    };
    events.onopen = () => {
      if (onState) onState(true);
    };
    events.addEventListener("update", receive);
    events.onerror = () => {
      if (onState) onState(false);
    };
    return () => events.close();
  }
  async function getPlayer() {
    const [status, song] = await Promise.all([
      call("MYMPD_API_PLAYER_STATE"),
      call("MYMPD_API_PLAYER_CURRENT_SONG").catch(() => ({}))
    ]);
    let player = normalizePlayer(status, song);
    if (isWebUri(player.song.uri) && !radioNames.has(normalizeUri(player.song.uri))) {
      await loadRadioNames().catch(() => {
      });
      player = normalizePlayer(status, song);
    }
    return player;
  }
  function normalizePlayer(status = {}, song = {}) {
    const uri = song.uri || song.Uri || "";
    return {
      state: status.state || "stop",
      volume: Number(status.volume === null || status.volume === void 0 ? 0 : status.volume),
      elapsed: Number(status.elapsedTime === null || status.elapsedTime === void 0 ? status.elapsed === null || status.elapsed === void 0 ? 0 : status.elapsed : status.elapsedTime),
      duration: Number(status.totalTime === null || status.totalTime === void 0 ? song.Duration === null || song.Duration === void 0 ? song.duration === null || song.duration === void 0 ? 0 : song.duration : song.Duration : status.totalTime),
      currentSongId: Number(status.currentSongId === null || status.currentSongId === void 0 ? song.id === null || song.id === void 0 ? -1 : song.id : status.currentSongId),
      random: mpdBoolean(status.random),
      repeat: mpdBoolean(status.repeat),
      single: mpdBoolean(status.single) ? "1" : "0",
      song: { uri, title: radioNames.get(normalizeUri(uri)) || readableTitle(song, uri), artist: song.Artist || song.AlbumArtist || "", album: song.Album || "" },
      cover: uri ? "/api/player/art?size=large&uri=".concat(encodeURIComponent(uri)) : "/art/album-placeholder.svg"
    };
  }
  async function albums(search = "") {
    const result = await call("MYMPD_API_DATABASE_ALBUM_LIST", { offset: 0, limit: 100, expression: search ? "((any contains '".concat(escapeMpd(search), "'))") : "", sort: "Album", sortdesc: false, fields: ["Album", "AlbumArtist"] });
    return result.data || [];
  }
  async function tracks(search) {
    const result = await call("MYMPD_API_DATABASE_SEARCH", { offset: 0, limit: 100, expression: "((any contains '".concat(escapeMpd(search), "'))"), sort: "Title", sortdesc: false, fields });
    return result.data || [];
  }
  async function albumTracks(albumId) {
    const result = await call("MYMPD_API_DATABASE_ALBUM_DETAIL", { albumid: albumId, fields });
    return result.data || [];
  }
  async function queue() {
    const result = await call("MYMPD_API_QUEUE_SEARCH", { offset: 0, limit: 1e3, expression: "", sort: "Priority", sortdesc: false, fields });
    return result.data || [];
  }
  async function playlists() {
    const result = await call("MYMPD_API_PLAYLIST_LIST", { offset: 0, limit: 500, searchstr: "", type: 0, sort: "Name", sortdesc: false, fields: ["Name", "Last-Modified"] });
    return result.data || [];
  }
  async function playlistTracks(plist) {
    const result = await call("MYMPD_API_PLAYLIST_CONTENT_LIST", { plist, offset: 0, limit: 1e3, expression: "", fields: playlistFields });
    return result.data || [];
  }
  async function radios(search = "") {
    const expression = search ? "((Name contains '".concat(escapeMpd(search), "'))") : "";
    const result = await call("MYMPD_API_WEBRADIO_FAVORITE_SEARCH", { offset: 0, limit: 1e3, expression, sort: "Name", sortdesc: false });
    const data = result.data || [];
    rememberRadioNames(data);
    return data;
  }
  var actions = {
    play: () => call("MYMPD_API_PLAYER_PLAY"),
    pause: () => call("MYMPD_API_PLAYER_PAUSE"),
    stop: () => call("MYMPD_API_PLAYER_STOP"),
    next: () => call("MYMPD_API_PLAYER_NEXT"),
    prev: () => call("MYMPD_API_PLAYER_PREV"),
    seek: (seconds) => call("MYMPD_API_PLAYER_SEEK_CURRENT", { seek: Math.round(seconds), relative: false }),
    volume: (volume) => call("MYMPD_API_PLAYER_VOLUME_SET", { volume: Math.round(volume) }),
    playbackMode: (options) => call("MYMPD_API_PLAYER_OPTIONS_SET", options),
    playSong: (songId) => call("MYMPD_API_PLAYER_PLAY_SONG", { songId: Number(songId) }),
    replaceUris: (uris) => call("MYMPD_API_QUEUE_REPLACE_URIS", { uris, play: true }),
    appendUris: (uris) => call("MYMPD_API_QUEUE_APPEND_URIS", { uris, play: false }),
    replacePlaylist: (plist) => call("MYMPD_API_QUEUE_REPLACE_PLAYLISTS", { plists: [plist], play: true }),
    removeQueue: (ids) => call("MYMPD_API_QUEUE_RM_IDS", { songIds: ids.map(Number) }),
    clearQueue: () => call("MYMPD_API_QUEUE_CLEAR"),
    addRandomQueue: () => call("MYMPD_API_QUEUE_ADD_RANDOM", { plist: "Database", quantity: 50, mode: 1, play: false }),
    appendPlaylistUris: (plist, uris) => call("MYMPD_API_PLAYLIST_CONTENT_APPEND_URIS", { plist, uris }),
    renamePlaylist: (plist, newName) => call("MYMPD_API_PLAYLIST_RENAME", { plist, newName }),
    removePlaylists: (plists) => call("MYMPD_API_PLAYLIST_RM", { plists }),
    removePlaylistPositions: (plist, positions) => call("MYMPD_API_PLAYLIST_CONTENT_RM_POSITIONS", { plist, positions: positions.map(Number).sort((a, b) => b - a) }),
    movePlaylistPosition: (plist, from, to) => call("MYMPD_API_PLAYLIST_CONTENT_MOVE_POSITION", { plist, from: Number(from), to: Number(to) })
  };
  function radioPlaylistUri(uri) {
    return "mympd://webradio/".concat(encodeURI(uri).replace(/[!'()*#?;:,@&=+$~]/g, (char) => "%".concat(char.charCodeAt(0).toString(16))));
  }
  function coverFor(item, radio = false) {
    if (radio) return item.Image ? rewriteAsset(item.Image) : "/art/radio-placeholder.svg";
    const uri = item.FirstSongUri || item.uri || item.Uri || "";
    return uri ? "/api/player/art?size=small&uri=".concat(encodeURIComponent(uri)) : "/art/album-placeholder.svg";
  }
  function rewriteAsset(uri) {
    return uri && uri.startsWith("/albumart") ? "/api/player/art?source=".concat(encodeURIComponent(uri)) : "/art/radio-placeholder.svg";
  }
  function escapeMpd(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  }
  function fileName(uri) {
    return decodeURIComponent(String(uri).split("/").pop() || "").replace(/\.[^.]+$/, "");
  }
  function isWebUri(value) {
    return /^https?:\/\//i.test(String(value || ""));
  }
  function normalizeUri(value) {
    return String(value || "").trim().replace(/\/$/, "");
  }
  function readableTitle(song, uri) {
    const title = song.Title || song.Name || "";
    return (title && !isWebUri(title) ? title : fileName(uri)) || "等待播放";
  }
  function rememberRadioNames(items) {
    items.forEach((item) => {
      if (item && item.StreamUri && item.Name) radioNames.set(normalizeUri(item.StreamUri), item.Name);
    });
  }
  async function loadRadioNames() {
    const result = await call("MYMPD_API_WEBRADIO_FAVORITE_SEARCH", { offset: 0, limit: 1e3, expression: "", sort: "Name", sortdesc: false });
    rememberRadioNames(result.data || []);
  }

  // control/static/js/player.js?v=20261002-ios2
  var initialized = false;
  var activeView = "now";
  var requestedView;
  var model;
  var refreshTimer;
  var searchTimer;
  var disconnectSocket;
  var externalSourceActive = null;
  var queueSignature = "";
  var focusedQueueSongId = null;
  function syncActiveSource(sources = []) {
    const active = sources.some((source) => String(source.id).toLowerCase() === "airplay" && source.status === "playing");
    if (active === externalSourceActive) return;
    externalSourceActive = active;
    const banner = $("#activeSourceBanner");
    if (!banner) return;
    banner.hidden = !externalSourceActive;
    $("#playerNow").classList.toggle("has-external-source", externalSourceActive);
    $("#playerSeek").disabled = externalSourceActive;
    $$("[data-player-action]").forEach((button) => {
      button.disabled = externalSourceActive;
    });
    $("#playerModeButton").disabled = externalSourceActive;
    const volume = document.querySelector(".player-volume-popover");
    volume.inert = externalSourceActive;
    if (externalSourceActive) volume.setAttribute("aria-disabled", "true");
    else volume.removeAttribute("aria-disabled");
    if (externalSourceActive) volume.removeAttribute("open");
  }
  function initPlayer() {
    if (initialized) return;
    initialized = true;
    activeView = requestedView || "now";
    $$("[data-player-view]").forEach((button) => button.onclick = () => openView(button.dataset.playerView));
    $$("[data-player-action]").forEach((button) => button.onclick = () => playerAction(button.dataset.playerAction));
    $("#playerModeButton").onclick = cyclePlaybackMode;
    $("#playerSeek").onchange = (event) => run(() => actions.seek(Number(event.target.value)));
    $("#playerVolume").oninput = (event) => {
      $("#playerVolumeValue").value = event.target.value;
    };
    $("#playerVolume").onchange = (event) => run(() => actions.volume(Number(event.target.value)), false);
    installThumbDragRange($("#playerSeek"));
    installThumbDragRange($("#playerVolume"));
    $("#playerSearch").oninput = (event) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => renderView(activeView, event.target.value.trim()), 280);
    };
    disconnectSocket = connectNotifications(() => scheduleRefresh(), (connected) => setEngineState(connected));
    syncViewChrome();
  }
  async function activatePlayer(force = false) {
    initPlayer();
    if (force || !model) await refreshPlayer();
    if (activeView !== "now") await renderView(activeView, $("#playerSearch").value.trim());
    startClock();
  }
  function resetPlayer() {
    model = null;
    clearInterval(refreshTimer);
    if (disconnectSocket) disconnectSocket();
    initialized = false;
    $("#playerContent").innerHTML = empty("播放器会话已结束", "重新登录后可继续使用曲库与歌单");
  }
  async function refreshPlayer() {
    try {
      model = await getPlayer();
      const song = model.song;
      setText($("#playerTitle"), song.title);
      setText($("#playerArtist"), [song.artist, song.album].filter(Boolean).join(" · ") || "从曲库、歌单或网络电台开始");
      setText($("#playerOrigin"), /^https?:/.test(song.uri) ? "网络音频" : "本地曲库");
      const cover = $("#playerCover");
      const coverChanged = cover.dataset.requestedCover !== model.cover;
      cover.onerror = () => {
        cover.onerror = null;
        cover.src = "/art/album-placeholder.svg";
      };
      if (coverChanged) {
        cover.dataset.requestedCover = model.cover;
        cover.src = model.cover;
      }
      $("#playerSeek").disabled = externalSourceActive || !(model.duration > 0);
      $("#playerSeek").max = Math.max(model.duration, 1);
      if (!isRangeInteracting($("#playerSeek"))) {
        $("#playerSeek").value = Math.min(model.elapsed, model.duration || 1);
        syncThumbDragRange($("#playerSeek"));
      }
      setText($("#playerDuration"), model.duration ? time(model.duration) : "直播");
      if (!isRangeInteracting($("#playerVolume"))) {
        $("#playerVolume").value = model.volume;
        syncThumbDragRange($("#playerVolume"));
      }
      $("#playerVolumeValue").value = model.volume;
      setHref($("#playerToggleIcon"), model.state === "play" ? "/icons.svg#icon-pause" : "/icons.svg#icon-play-filled");
      syncPlaybackMode();
      document.querySelector(".lightfield-player").classList.toggle("is-playing", model.state === "play");
      if (coverChanged) extractAccent(cover);
      setEngineState(true);
    } catch (error) {
      setEngineState(false);
      toast(error.message, true);
    }
  }
  async function openView(view) {
    activeView = view;
    $("#playerSearch").value = "";
    {
      const playAll = $(".player-content-head .play-all");
      if (playAll) playAll.remove();
    }
    syncViewChrome();
    if (view === "now") return;
    await renderView(view, "");
  }
  function syncViewChrome() {
    document.querySelector(".lightfield-player").dataset.playerView = activeView;
    $$("[data-player-view]").forEach((button) => button.classList.toggle("active", button.dataset.playerView === activeView));
    const names = { now: ["NOW PLAYING", "正在播放"], queue: ["UP NEXT", "播放队列"], playlists: ["PLAYLISTS", "歌单"], radio: ["BROADCAST", "网络电台"], library: ["COLLECTION", "曲库"] };
    [$("#playerViewEyebrow").textContent, $("#playerViewTitle").textContent] = names[activeView];
    $("#playerSearch").hidden = activeView !== "library" && activeView !== "radio";
  }
  async function renderView(view, query = "") {
    if (view !== "playlists") {
      const playAll = $(".player-content-head .play-all");
      if (playAll) playAll.remove();
    }
    const content = $("#playerContent");
    content.setAttribute("aria-busy", "true");
    content.innerHTML = '<div class="player-loading"><span></span><b>正在读取'.concat(esc($("#playerViewTitle").textContent), "</b></div>");
    try {
      if (view === "queue") return renderQueue();
      if (view === "playlists") return renderPlaylists();
      if (view === "radio") return renderRadios(query);
      if (view === "library") return renderLibrary(query);
    } catch (error) {
      content.innerHTML = empty("暂时无法读取", error.message, true);
    } finally {
      content.setAttribute("aria-busy", "false");
    }
  }
  async function renderLibrary(query) {
    if (query.length > 1) return renderSearchResults(query);
    const albums2 = await albums();
    $("#playerContent").innerHTML = albums2.length ? '<div class="album-grid">'.concat(albums2.map((album, index) => '<button class="album-card" data-album="'.concat(esc(album.AlbumId || album.albumId || ""), '" data-index="').concat(index, '"><img src="').concat(esc(coverFor(album)), '" alt="" loading="lazy"><span><b>').concat(esc(album.Album || "未知专辑"), "</b><small>").concat(esc(album.AlbumArtist || album.Artist || "未知艺术家"), "</small></span></button>")).join(""), "</div>") : empty("曲库还是空的", "在 myMPD 更新曲库后，专辑会出现在这里");
    installArtworkFallback(".album-card img", "/art/album-placeholder.svg");
    $$("[data-album]", $("#playerContent")).forEach((button) => button.onclick = async () => renderTracks(await albumTracks(button.dataset.album), "专辑中没有曲目"));
  }
  async function renderQueue() {
    const items = await queue();
    renderTracks(items, "队列为空", { queue: true });
    queueSignature = queueItemsSignature(items);
    const button = document.createElement("button");
    button.className = "play-all random-queue";
    button.innerHTML = "".concat(icon("shuffle"), "随机 50 首");
    button.onclick = async () => {
      button.disabled = true;
      const updated = await run(async () => {
        await actions.clearQueue();
        await actions.addRandomQueue();
      });
      if (updated) await refreshQueue(true);
      button.disabled = false;
    };
    $(".player-content-head").append(button);
    syncQueueCurrent(true);
  }
  async function refreshQueue(focusCurrent = false) {
    const items = await queue();
    const signature = queueItemsSignature(items);
    if (signature !== queueSignature) {
      const scrollTop = $("#playerContent").scrollTop;
      renderTracks(items, "队列为空", { queue: true });
      queueSignature = signature;
      if (!focusCurrent) $("#playerContent").scrollTop = scrollTop;
    }
    syncQueueCurrent(focusCurrent);
  }
  function queueItemsSignature(items) {
    return JSON.stringify(items.map((item) => [item.id, item.Pos, item.uri || item.Uri, item.Title || item.Name, item.Duration || item.duration]));
  }
  function syncQueueCurrent(forceFocus = false) {
    const currentId = String(model && model.currentSongId !== null && model.currentSongId !== void 0 ? model.currentSongId : "");
    $$(".track-row[data-song-id]", $("#playerContent")).forEach((row2) => row2.classList.toggle("is-current", row2.dataset.songId === currentId));
    const row = $(".track-row.is-current", $("#playerContent"));
    if (!row || !forceFocus && focusedQueueSongId === currentId) return;
    focusedQueueSongId = currentId;
    requestAnimationFrame(() => {
      const content = $("#playerContent");
      content.scrollTo({ top: Math.max(0, row.offsetTop - row.offsetHeight * 3), behavior: "smooth" });
    });
  }
  function renderTracks(items, title, options = {}) {
    const { queue: queue2 = false, selectable = false, playlist = "" } = options;
    $("#playerContent").innerHTML = items.length ? '<div class="track-list'.concat(selectable ? " is-selectable" : "", '">').concat(items.map((item, index) => {
      const uri = item.uri || item.Uri || "";
      const position = Number(item.Pos === null || item.Pos === void 0 ? index : item.Pos);
      const selection = selectable ? '<label class="track-select"><input type="checkbox" data-track-select data-uri="'.concat(esc(uri), '" data-position="').concat(position, '" aria-label="选择 ').concat(esc(item.Title || item.Name || "曲目"), '"><span></span></label>') : "";
      const action = queue2 ? '<button class="track-remove" data-remove-id="'.concat(esc(item.id), '" aria-label="从队列移除">').concat(icon("close"), "</button>") : playlist ? '<span class="track-order"><button data-move-from="'.concat(position, '" data-move-to="').concat(Math.max(0, position - 1), '" aria-label="上移" ').concat(index === 0 ? "disabled" : "", '>↑</button><button data-move-from="').concat(position, '" data-move-to="').concat(position + 1, '" aria-label="下移" ').concat(index === items.length - 1 ? "disabled" : "", ">↓</button></span>") : '<button class="track-add" data-add-uri="'.concat(esc(uri), '" aria-label="加入队列">').concat(icon("plus"), "</button>");
      return '<article class="track-row'.concat(selectable ? " has-selection" : "").concat(playlist ? " has-order" : "").concat(Number(item.id) === (model && model.currentSongId) ? " is-current" : "", '"').concat(queue2 ? ' data-song-id="'.concat(esc(item.id === null || item.id === void 0 ? "" : item.id), '"') : "", ">").concat(selection, '<button class="track-play" data-play-id="').concat(esc(item.id === null || item.id === void 0 ? "" : item.id), '" data-uri="').concat(esc(uri), '" aria-label="播放 ').concat(esc(item.Title || item.Name || "曲目"), '">').concat(icon("play-filled"), '</button><span class="track-index">').concat(String(index + 1).padStart(2, "0"), "</span><div><b>").concat(esc(item.Title || item.Name || "未知曲目"), "</b><small>").concat(esc([item.Artist || item.AlbumArtist, item.Album].filter(Boolean).join(" · ")), "</small></div><time>").concat(time(item.Duration || item.duration || 0), "</time>").concat(action, "</article>");
    }).join(""), "</div>") : empty(title, "换一个分类或搜索词试试");
    $$("[data-play-id]", $("#playerContent")).forEach((button) => button.onclick = () => run(() => button.dataset.playId ? actions.playSong(button.dataset.playId) : actions.replaceUris([button.dataset.uri])));
    $$("[data-add-uri]", $("#playerContent")).forEach((button) => button.onclick = () => run(() => actions.appendUris([button.dataset.addUri])));
    $$("[data-remove-id]", $("#playerContent")).forEach((button) => button.onclick = () => run(() => actions.removeQueue([button.dataset.removeId])).then(() => renderView("queue")));
    if (playlist) $$("[data-move-from]", $("#playerContent")).forEach((button) => button.onclick = async () => {
      if (await run(() => actions.movePlaylistPosition(playlist, button.dataset.moveFrom, button.dataset.moveTo), false)) await showPlaylist(playlist);
    });
  }
  async function renderSearchResults(query) {
    const [items, lists] = await Promise.all([tracks(query), playlists()]);
    renderTracks(items, "没有匹配曲目", { selectable: true });
    if (items.length) installSelectionBar(lists);
  }
  function installSelectionBar(lists, playlist = "") {
    const bar = document.createElement("section");
    bar.className = "selection-bar";
    bar.innerHTML = '<label><input type="checkbox" data-select-all><span>全选</span></label><b data-selection-count>已选 0 首</b>'.concat(playlist ? "<button data-remove-selected disabled>".concat(icon("close"), "移出歌单</button>") : '<select data-playlist-target aria-label="选择已有歌单"><option value="">选择已有歌单</option>'.concat(lists.map((item) => '<option value="'.concat(esc(item.uri || item.Name), '">').concat(esc(item.Name || item.uri), "</option>")).join(""), "</select><button data-add-existing disabled>加入歌单</button><button data-add-new disabled>").concat(icon("plus"), "新建歌单</button>"));
    $("#playerContent").prepend(bar);
    const boxes = $$("[data-track-select]", $("#playerContent"));
    const selected = () => boxes.filter((box) => box.checked);
    const sync = () => {
      const count = selected().length;
      $("[data-selection-count]", bar).textContent = "已选 ".concat(count, " 首");
      $$("button", bar).forEach((button) => {
        button.disabled = !count;
      });
      const addExisting = $("[data-add-existing]", bar), target = $("[data-playlist-target]", bar);
      if (addExisting) addExisting.disabled = !count || !target.value;
      $("[data-select-all]", bar).checked = count > 0 && count === boxes.length;
      $("[data-select-all]", bar).indeterminate = count > 0 && count < boxes.length;
    };
    boxes.forEach((box) => box.onchange = sync);
    $("[data-select-all]", bar).onchange = (event) => {
      boxes.forEach((box) => {
        box.checked = event.target.checked;
      });
      sync();
    };
    if (playlist) {
      $("[data-remove-selected]", bar).onclick = async () => {
        const positions = selected().map((box) => box.dataset.position);
        if (await run(() => actions.removePlaylistPositions(playlist, positions))) await showPlaylist(playlist);
      };
      return;
    }
    $("[data-playlist-target]", bar).onchange = (event) => {
      $("[data-add-existing]", bar).disabled = !selected().length || !event.target.value;
    };
    $("[data-add-existing]", bar).onclick = async () => {
      const target = $("[data-playlist-target]", bar).value;
      if (target && await addSelectionToPlaylist(target, selected())) sync();
    };
    $("[data-add-new]", bar).onclick = async () => {
      const name = await askPlaylistName("新建歌单", "");
      if (name && await addSelectionToPlaylist(name, selected())) sync();
    };
  }
  async function addSelectionToPlaylist(plist, boxes) {
    const uris = boxes.map((box) => box.dataset.uri).filter(Boolean);
    if (!uris.length) return false;
    const ok = await run(() => actions.appendPlaylistUris(plist, uris));
    if (ok) boxes.forEach((box) => {
      box.checked = false;
    });
    return ok;
  }
  async function renderPlaylists() {
    {
      const playAll = $(".player-content-head .play-all");
      if (playAll) playAll.remove();
    }
    const lists = await playlists();
    $("#playerContent").innerHTML = lists.length ? '<div class="playlist-grid">'.concat(lists.map((item) => {
      const plist = item.uri || item.Name || "";
      const name = item.Name || item.Playlist || plist;
      return '<article class="playlist-card"><button data-plist="'.concat(esc(plist), '"><span>').concat(icon("playlist"), "</span><div><b>").concat(esc(name || "未命名歌单"), "</b><small>打开歌单</small></div>").concat(icon("chevron-right"), "</button></article>");
    }).join(""), "</div>") : empty("还没有歌单", "从曲库搜索歌曲后可创建第一个歌单");
    $$("[data-plist]", $("#playerContent")).forEach((button) => button.onclick = async () => {
      if (!button.dataset.plist) return toast("歌单名称无效", true);
      try {
        await showPlaylist(button.dataset.plist);
      } catch (error) {
        toast(error.message, true, 5e3);
      }
    });
  }
  async function showPlaylist(plist) {
    const tracks2 = await playlistTracks(plist);
    renderTracks(tracks2, "歌单为空", { selectable: true, playlist: plist });
    const head = document.createElement("section");
    head.className = "playlist-edit-head";
    head.innerHTML = "<button data-playlist-back>".concat(icon("collapse"), "返回歌单</button><strong>").concat(esc(plist), "</strong><span><button data-playlist-rename>").concat(icon("edit"), "重命名</button><button data-playlist-delete>").concat(icon("close"), "删除</button></span>");
    if (tracks2.length) installSelectionBar([], plist);
    $("#playerContent").prepend(head);
    addPlayAll(plist, true);
    $("[data-playlist-back]", head).onclick = () => renderView("playlists");
    $("[data-playlist-rename]", head).onclick = async () => {
      const name = await askPlaylistName("重命名歌单", plist);
      if (name && name !== plist && await run(() => actions.renamePlaylist(plist, name))) await showPlaylist(name);
    };
    $("[data-playlist-delete]", head).onclick = async () => {
      if (!await askConfirm("删除歌单？", "将通过 myMPD 删除“".concat(plist, "”，音乐文件不会被删除。"))) return;
      if (await run(() => actions.removePlaylists([plist]))) await renderView("playlists");
    };
  }
  async function renderRadios(query) {
    const radios2 = await radios(query);
    $("#playerContent").innerHTML = radios2.length ? '<div class="radio-grid">'.concat(radios2.map((item) => '<button class="radio-card" data-radio="'.concat(esc(item.StreamUri), '"><img src="').concat(esc(coverFor(item, true)), '" alt="" loading="lazy"><span class="radio-live"><i></i>LIVE</span><div><b>').concat(esc(item.Name), "</b><small>").concat(esc([item.Country, ...item.Genres || []].filter(Boolean).join(" · ") || "网络电台"), "</small></div>").concat(icon("play-filled"), "</button>")).join(""), "</div>") : empty("没有匹配电台", "检查 myMPD 网络电台收藏");
    installArtworkFallback(".radio-card img", "/art/radio-placeholder.svg");
    $$("[data-radio]", $("#playerContent")).forEach((button) => button.onclick = () => run(() => actions.replacePlaylist(radioPlaylistUri(button.dataset.radio))));
  }
  function addPlayAll(value, playlist) {
    const head = $(".player-content-head");
    const existing = head.querySelector(".play-all");
    if (existing) existing.remove();
    const button = document.createElement("button");
    button.className = "play-all";
    button.innerHTML = "".concat(icon("play-filled"), "播放全部");
    button.onclick = () => run(() => playlist ? actions.replacePlaylist(value) : actions.replaceUris(value));
    head.append(button);
  }
  async function playerAction(action) {
    const fn = action === "toggle" ? model && model.state === "play" ? actions.pause : actions.play : actions[action];
    if (fn) await run(fn);
  }
  function currentPlaybackMode() {
    if (model && model.random) return "shuffle";
    if (model && model.single === "1") return "repeat-one";
    if (model && model.repeat) return "repeat-all";
    return "order";
  }
  function syncPlaybackMode() {
    const modes = {
      order: ["顺序播放", "queue"],
      "repeat-all": ["列表循环", "repeat"],
      "repeat-one": ["单曲循环", "repeat-one"],
      shuffle: ["随机循环", "shuffle"]
    };
    const mode = currentPlaybackMode();
    const [label, iconName] = modes[mode];
    const button = $("#playerModeButton");
    if (button.dataset.mode === mode) return;
    button.dataset.mode = mode;
    button.setAttribute("aria-label", "".concat(label, "，点击切换"));
    button.title = label;
    setHref($("#playerModeIcon"), "/icons.svg#icon-".concat(iconName));
  }
  async function cyclePlaybackMode() {
    const order = ["order", "repeat-all", "repeat-one", "shuffle"];
    const next = order[(order.indexOf(currentPlaybackMode()) + 1) % order.length];
    const options = {
      order: { repeat: false, random: false, single: "0" },
      "repeat-all": { repeat: true, random: false, single: "0" },
      "repeat-one": { repeat: true, random: false, single: "1" },
      shuffle: { repeat: true, random: true, single: "0" }
    };
    await run(() => actions.playbackMode(options[next]));
  }
  async function run(fn) {
    try {
      await fn();
      await refreshPlayer();
      return true;
    } catch (error) {
      toast(error.message, true, 5e3);
      return false;
    }
  }
  function scheduleRefresh() {
    clearTimeout(scheduleRefresh.timer);
    scheduleRefresh.timer = setTimeout(async () => {
      try {
        await refreshPlayer();
        if (activeView === "queue") await refreshQueue();
      } catch (error) {
        setEngineState(false);
      }
    }, 180);
  }
  function startClock() {
    clearInterval(refreshTimer);
    refreshTimer = setInterval(() => {
      if (!model) return;
      if (model.state === "play") model.elapsed = Math.min(model.duration || Infinity, model.elapsed + 0.25);
      if (!isRangeInteracting($("#playerSeek"))) {
        $("#playerSeek").value = model.elapsed;
        syncThumbDragRange($("#playerSeek"));
      }
      $("#playerElapsed").textContent = time(model.elapsed);
    }, 250);
  }
  function setEngineState(ok) {
    const node = $("#playerEngineState");
    if (node.dataset.online === String(ok)) return;
    node.dataset.online = String(ok);
    node.classList.toggle("online", ok);
    node.querySelector("span").textContent = ok ? "音乐引擎在线" : "正在重连";
  }
  function setText(node, value) {
    if (node.textContent !== String(value)) node.textContent = value;
  }
  function setHref(node, value) {
    if (node.getAttribute("href") !== value) node.setAttribute("href", value);
  }
  function isRangeInteracting(input) {
    return document.activeElement === input || input.dataset.dragging === "true";
  }
  function empty(title, copy, error = false) {
    return '<div class="player-empty'.concat(error ? " is-error" : "", '"><img src="/art/empty-state.svg" alt=""><h3>').concat(esc(title), "</h3><p>").concat(esc(copy), "</p></div>");
  }
  function time(seconds) {
    const n = Math.max(0, Math.floor(Number(seconds) || 0));
    return "".concat(Math.floor(n / 60), ":").concat(String(n % 60).padStart(2, "0"));
  }
  function installArtworkFallback(selector, fallback) {
    $$(selector, $("#playerContent")).forEach((image) => image.addEventListener("error", () => {
      if (!image.src.endsWith(fallback)) image.src = fallback;
    }, { once: true }));
  }
  function askPlaylistName(title, value) {
    return new Promise((resolve) => {
      const dialog = document.createElement("div");
      dialog.className = "modal playlist-name-dialog";
      dialog.setAttribute("role", "dialog");
      dialog.setAttribute("aria-modal", "true");
      dialog.innerHTML = '<form class="dialog-card compact-dialog"><h2>'.concat(esc(title), '</h2><label><span>歌单名称</span><input name="playlistName" maxlength="200" value="').concat(esc(value), '" required autocomplete="off"></label><div class="dialog-actions"><button type="button" class="secondary" data-cancel>取消</button><button class="accent-btn">确定</button></div></form>');
      document.body.append(dialog);
      const finish = (result) => {
        closeDialog(dialog);
        dialog.remove();
        resolve(result);
      };
      $("[data-cancel]", dialog).onclick = () => finish("");
      $("form", dialog).onsubmit = (event) => {
        event.preventDefault();
        finish(event.currentTarget.elements.playlistName.value.trim());
      };
      dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        finish("");
      }, { once: true });
      openDialog(dialog);
      $("input", dialog).select();
    });
  }
  function extractAccent(image) {
    if (!image.complete || !image.naturalWidth) {
      image.addEventListener("load", () => extractAccent(image), { once: true });
      return;
    }
    try {
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d", { willReadFrequently: true });
      canvas.width = canvas.height = 12;
      context.drawImage(image, 0, 0, 12, 12);
      const pixels = context.getImageData(0, 0, 12, 12).data;
      const samples = Array.from({ length: Math.ceil(pixels.length / 16) }, (_, index) => index * 16).filter((index) => pixels[index + 3] >= 150);
      if (!samples.length) return;
      const totals = samples.reduce((sum, index) => [sum[0] + pixels[index], sum[1] + pixels[index + 1], sum[2] + pixels[index + 2]], [0, 0, 0]);
      document.documentElement.style.setProperty("--player-accent", totals.map((value) => Math.round(value / samples.length)).join(" "));
    } catch (e) {
    }
  }

  // control/static/app.js
  var pollTimer;
  var bootstrapped = false;
  async function start() {
    if (window.__snapProbe) window.__snapProbe("app-start");
    document.documentElement.dataset.consoleBoot = "starting";
    initEvents();
    await checkAuth();
  }
  async function checkAuth() {
    try {
      state.auth = await request("/api/auth");
      if (window.__snapProbe) window.__snapProbe("auth-loaded");
      $("#loginUsername").value = state.auth.username || "admin";
      $("#accountState").textContent = state.auth.enabled ? "已启用认证 · ".concat(state.auth.username || "admin") : "可信家庭 LAN 模式 · 未启用认证";
      $("#logoutButton").hidden = !state.auth.enabled;
      if (state.auth.enabled && (!state.auth.configured || !state.auth.authenticated)) {
        if (!state.auth.configured) $("#loginHint").textContent = "服务端尚未设置 CONTROL_PASSWORD，请先完成部署配置。";
        document.documentElement.dataset.consoleBoot = "auth";
        if (window.__snapProbe) window.__snapProbe("login-visible");
        openLogin();
        return false;
      }
      closeDialog("#loginDialog");
      bootstrapped = true;
      await refreshState();
      await activatePlayer();
      document.documentElement.dataset.consoleBoot = "ready";
      if (window.__snapProbe) window.__snapProbe("console-ready");
      startPolling();
      return true;
    } catch (error) {
      document.documentElement.dataset.consoleBoot = "failed";
      if (window.__snapProbe) window.__snapProbe("app-failed");
      toast(error.message, true);
      return false;
    }
  }
  function openLogin() {
    const dialog = $("#loginDialog");
    openDialog(dialog);
  }
  function clearPrivateState(message = "登录状态已失效，请重新登录。") {
    state.zones = [];
    state.mainGroup = null;
    state.sources = [];
    syncActiveSource([]);
    renderZones(true);
    $("#deviceCount").textContent = "0";
    $("#devicePanelHost").innerHTML = '<section class="state-panel"><svg class="state-mark" aria-hidden="true"><use href="/icons.svg#icon-speaker"/></svg><h2>需要重新登录</h2><p>'.concat(message, "</p></section>");
    $("#dashboard").setAttribute("aria-busy", "false");
    resetPlayer();
  }
  function showConnectionError(message) {
    $("#devicePanelHost").innerHTML = '<section class="state-panel is-error"><svg class="state-mark" aria-hidden="true"><use href="/icons.svg#icon-network"/></svg><h2>网关连接中断</h2><p>'.concat(message || "无法读取设备状态，请检查网关服务和网络连接。", '</p><div class="state-actions"><button class="secondary-btn" data-retry-state>重新连接</button></div></section>');
    $("#dashboard").setAttribute("aria-busy", "false");
    $("[data-retry-state]", $("#dashboard")).onclick = refreshState;
  }
  async function login(event) {
    event.preventDefault();
    try {
      await post("/api/login", { username: $("#loginUsername").value, password: $("#loginPassword").value });
      state.auth.authenticated = true;
      $("#loginPassword").value = "";
      closeDialog("#loginDialog");
      await checkAuth();
    } catch (error) {
      $("#loginHint").textContent = error.message;
      $("#loginPassword").select();
    }
  }
  async function refreshState() {
    if (!bootstrapped) return;
    try {
      const data = await request("/api/state");
      state.sources = data.sources || data.snapcast && data.snapcast.streams || [];
      syncActiveSource(state.sources);
      state.zones = data.zones || data.snapcast && data.snapcast.groups || [];
      state.mainGroup = data.mainGroup || data.snapcast && data.snapcast.mainGroup || null;
      state.system = __spreadValues(__spreadValues({}, state.system), data.system || {});
      state.system.healthy = Boolean(state.system.ok) && !(data.errors && data.errors.length);
      $("#dashboard").setAttribute("aria-busy", "false");
      $("#healthLamp").classList.toggle("ok", state.system.healthy);
      $("#healthText").textContent = state.system.healthy ? "系统正常" : "部分服务异常";
      const components = state.system.components || {};
      for (const [name, id] of [["snapserver", "#healthSnapserver"], ["mpd", "#healthMpd"], ["mympd", "#healthMympd"]]) {
        const node = $(id);
        node.textContent = components[name] ? "正常" : "异常";
        node.classList.toggle("ok", Boolean(components[name]));
      }
      $("#gatewayName").textContent = state.system.hostname || "本机网关";
      renderZones(Boolean($("#dashboard .state-panel.is-error")));
    } catch (error) {
      if (error.status === 401) {
        state.auth.authenticated = false;
        bootstrapped = false;
        clearInterval(pollTimer);
        clearPrivateState();
        openLogin();
        return;
      }
      $("#healthLamp").classList.remove("ok");
      $("#healthText").textContent = "连接中断";
      showConnectionError(error.message);
    }
  }
  function initEvents() {
    installMobileGestureGuard();
    document.addEventListener("auth-required", () => {
      if (!state.auth.authenticated && !bootstrapped) return openLogin();
      state.auth.authenticated = false;
      bootstrapped = false;
      clearInterval(pollTimer);
      clearPrivateState();
      openLogin();
    });
    document.addEventListener("state-refresh", refreshState);
    document.addEventListener("click", (event) => {
      const close = event.target.closest("[data-close-dialog]");
      if (close) closeDialog(close.closest('[role="dialog"]'));
    });
    $("#loginForm").onsubmit = login;
    $("#loginDialog").addEventListener("cancel", (event) => event.preventDefault());
    $("#loginDialog").addEventListener("close", () => {
      if (state.auth.enabled && !state.auth.authenticated) Promise.resolve().then(openLogin);
    });
    $("#refreshRooms").onclick = refreshState;
    $("#logoutButton").onclick = logout;
  }
  function installMobileGestureGuard() {
    let gesture = null;
    document.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "touch") return;
      gesture = { x: event.clientX, y: event.clientY, moved: false, target: event.target };
    }, { capture: true, passive: true });
    document.addEventListener("pointermove", (event) => {
      if (!gesture || event.pointerType !== "touch") return;
      if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 10) gesture.moved = true;
    }, { capture: true, passive: true });
    document.addEventListener("pointerup", (event) => {
      if (!gesture || event.pointerType !== "touch") return;
      if (gesture.moved) {
        const interactive = gesture.target.closest ? gesture.target.closest("button, a, summary, input[type=range], .speaker-toggle") : null;
        if (interactive) interactive.dataset.ignoreTouchClickUntil = String(performance.now() + 450);
      }
      gesture = null;
    }, { capture: true, passive: true });
    document.addEventListener("pointercancel", () => {
      gesture = null;
    }, { capture: true, passive: true });
    document.addEventListener("click", (event) => {
      const interactive = event.target.closest ? event.target.closest("button, a, summary, input[type=range], .speaker-toggle") : null;
      if (Number(interactive && interactive.dataset.ignoreTouchClickUntil || 0) <= performance.now()) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    }, true);
  }
  async function logout() {
    try {
      await post("/api/logout", {});
    } catch (e) {
    }
    state.auth.authenticated = false;
    bootstrapped = false;
    clearInterval(pollTimer);
    clearPrivateState("已安全退出，设备与播放状态已从页面清除。");
    openLogin();
  }
  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(refreshState, 4e3);
  }
  document.addEventListener("visibilitychange", () => {
    clearInterval(pollTimer);
    if (!document.hidden && bootstrapped) {
      refreshState();
      startPolling();
    }
  });
  start();
})();
