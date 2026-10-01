import * as mpd from "./mympd-adapter.js?v=20260928-sync";
import { $, $$, askConfirm, esc, icon, installThumbDragRange, syncThumbDragRange, toast } from "./ui.js";

let initialized = false, activeView = "now", requestedView, model, refreshTimer, searchTimer, disconnectSocket;
let externalSourceActive = null;
let queueSignature = "", focusedQueueSongId = null;

export function syncActiveSource(sources = []) {
  const active = sources.some(source => String(source.id).toLowerCase() === "airplay" && source.status === "playing");
  if (active === externalSourceActive) return;
  externalSourceActive = active;
  const banner = $("#activeSourceBanner");
  if (!banner) return;
  banner.hidden = !externalSourceActive;
  $("#playerNow").classList.toggle("has-external-source", externalSourceActive);
  $("#playerSeek").disabled = externalSourceActive;
  $$('[data-player-action]').forEach(button => { button.disabled = externalSourceActive; });
  $("#playerModeButton").disabled = externalSourceActive;
  const volume = document.querySelector(".player-volume-popover");
  volume.inert = externalSourceActive;
  volume.toggleAttribute("aria-disabled", externalSourceActive);
  if (externalSourceActive) volume.removeAttribute("open");
}

export function initPlayer() {
  if (initialized) return;
  initialized = true;
  activeView = requestedView || "now";
  $$('[data-player-view]').forEach(button => button.onclick = () => openView(button.dataset.playerView));
  $$('[data-player-action]').forEach(button => button.onclick = () => playerAction(button.dataset.playerAction));
  $("#playerModeButton").onclick = cyclePlaybackMode;
  $("#playerSeek").onchange = event => run(() => mpd.actions.seek(Number(event.target.value)));
  $("#playerVolume").oninput = event => { $("#playerVolumeValue").value = event.target.value; };
  $("#playerVolume").onchange = event => run(() => mpd.actions.volume(Number(event.target.value)), false);
  installThumbDragRange($("#playerSeek"));
  installThumbDragRange($("#playerVolume"));
  $("#playerSearch").oninput = event => { clearTimeout(searchTimer); searchTimer = setTimeout(() => renderView(activeView, event.target.value.trim()), 280); };
  disconnectSocket = mpd.connectNotifications(() => scheduleRefresh(), connected => setEngineState(connected));
  syncViewChrome();
}

export async function activatePlayer(force = false) {
  initPlayer();
  if (force || !model) await refreshPlayer();
  if (activeView !== "now") await renderView(activeView, $("#playerSearch").value.trim());
  startClock();
}

export function resetPlayer() {
  model = null; clearInterval(refreshTimer); disconnectSocket?.(); initialized = false;
  $("#playerContent").innerHTML = empty("播放器会话已结束", "重新登录后可继续使用曲库与歌单");
}

async function refreshPlayer() {
  try {
    model = await mpd.getPlayer();
    const song = model.song;
    setText($("#playerTitle"), song.title);
    setText($("#playerArtist"), [song.artist, song.album].filter(Boolean).join(" · ") || "从曲库、歌单或网络电台开始");
    setText($("#playerOrigin"), /^https?:/.test(song.uri) ? "网络音频" : "本地曲库");
    const cover = $("#playerCover");
    const coverChanged = cover.dataset.requestedCover !== model.cover;
    cover.onerror = () => { cover.onerror = null; cover.src = "/art/album-placeholder.svg"; };
    if (coverChanged) { cover.dataset.requestedCover = model.cover; cover.src = model.cover; }
    $("#playerSeek").disabled = externalSourceActive || !(model.duration > 0);
    $("#playerSeek").max = Math.max(model.duration, 1);
    if (!isRangeInteracting($("#playerSeek"))) { $("#playerSeek").value = Math.min(model.elapsed, model.duration || 1); syncThumbDragRange($("#playerSeek")); }
    setText($("#playerDuration"), model.duration ? time(model.duration) : "直播");
    if (!isRangeInteracting($("#playerVolume"))) { $("#playerVolume").value = model.volume; syncThumbDragRange($("#playerVolume")); }
    $("#playerVolumeValue").value = model.volume;
    setHref($("#playerToggleIcon"), model.state === "play" ? "/icons.svg#icon-pause" : "/icons.svg#icon-play-filled");
    syncPlaybackMode();
    document.querySelector(".lightfield-player").classList.toggle("is-playing", model.state === "play");
    if (coverChanged) extractAccent(cover);
    setEngineState(true);
  } catch (error) { setEngineState(false); toast(error.message, true); }
}

async function openView(view) {
  activeView = view; $("#playerSearch").value = "";
  $(".player-content-head .play-all")?.remove();
  syncViewChrome();
  if (view === "now") return;
  await renderView(view, "");
}

function syncViewChrome() {
  document.querySelector(".lightfield-player").dataset.playerView = activeView;
  $$('[data-player-view]').forEach(button => button.classList.toggle("active", button.dataset.playerView === activeView));
  const names = { now: ["NOW PLAYING", "正在播放"], queue: ["UP NEXT", "播放队列"], playlists: ["PLAYLISTS", "歌单"], radio: ["BROADCAST", "网络电台"], library: ["COLLECTION", "曲库"] };
  [$("#playerViewEyebrow").textContent, $("#playerViewTitle").textContent] = names[activeView];
  $("#playerSearch").hidden = activeView !== "library" && activeView !== "radio";
}

export function openPlayerView(view) {
  if (!["now", "queue", "playlists", "radio", "library"].includes(view)) return;
  requestedView = activeView = view;
  if (initialized) syncViewChrome();
}

async function renderView(view, query = "") {
  if (view !== "playlists") $(".player-content-head .play-all")?.remove();
  const content = $("#playerContent"); content.setAttribute("aria-busy", "true"); content.innerHTML = `<div class="player-loading"><span></span><b>正在读取${esc($("#playerViewTitle").textContent)}</b></div>`;
  try {
    if (view === "queue") return renderQueue();
    if (view === "playlists") return renderPlaylists();
    if (view === "radio") return renderRadios(query);
    if (view === "library") return renderLibrary(query);
  } catch (error) { content.innerHTML = empty("暂时无法读取", error.message, true); }
  finally { content.setAttribute("aria-busy", "false"); }
}

async function renderLibrary(query) {
  if (query.length > 1) return renderSearchResults(query);
  const albums = await mpd.albums();
  $("#playerContent").innerHTML = albums.length ? `<div class="album-grid">${albums.map((album, index) => `<button class="album-card" data-album="${esc(album.AlbumId || album.albumId || "")}" data-index="${index}"><img src="${esc(mpd.coverFor(album))}" alt="" loading="lazy"><span><b>${esc(album.Album || "未知专辑")}</b><small>${esc(album.AlbumArtist || album.Artist || "未知艺术家")}</small></span></button>`).join("")}</div>` : empty("曲库还是空的", "在 myMPD 更新曲库后，专辑会出现在这里");
  installArtworkFallback(".album-card img", "/art/album-placeholder.svg");
  $$('[data-album]', $("#playerContent")).forEach(button => button.onclick = async () => renderTracks(await mpd.albumTracks(button.dataset.album), "专辑中没有曲目"));
}

async function renderQueue() {
  const items = await mpd.queue();
  renderTracks(items, "队列为空", { queue: true });
  queueSignature = queueItemsSignature(items);
  const button = document.createElement("button");
  button.className = "play-all random-queue";
  button.innerHTML = `${icon("shuffle")}随机 50 首`;
  button.onclick = async () => {
    button.disabled = true;
    const updated = await run(async () => {
      await mpd.actions.clearQueue();
      await mpd.actions.addRandomQueue();
    });
    if (updated) await refreshQueue(true);
    button.disabled = false;
  };
  $(".player-content-head").append(button);
  syncQueueCurrent(true);
}

async function refreshQueue(focusCurrent = false) {
  const items = await mpd.queue();
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
  return JSON.stringify(items.map(item => [item.id, item.Pos, item.uri || item.Uri, item.Title || item.Name, item.Duration || item.duration]));
}

function syncQueueCurrent(forceFocus = false) {
  const currentId = String(model?.currentSongId ?? "");
  $$(".track-row[data-song-id]", $("#playerContent")).forEach(row => row.classList.toggle("is-current", row.dataset.songId === currentId));
  const row = $(".track-row.is-current", $("#playerContent"));
  if (!row || (!forceFocus && focusedQueueSongId === currentId)) return;
  focusedQueueSongId = currentId;
  requestAnimationFrame(() => {
    const content = $("#playerContent");
    content.scrollTo({ top: Math.max(0, row.offsetTop - row.offsetHeight * 3), behavior: "smooth" });
  });
}

function renderTracks(items, title, options = {}) {
  const { queue = false, selectable = false, playlist = "" } = options;
  $("#playerContent").innerHTML = items.length ? `<div class="track-list${selectable ? " is-selectable" : ""}">${items.map((item, index) => {
    const uri = item.uri || item.Uri || "";
    const position = Number(item.Pos ?? index);
    const selection = selectable ? `<label class="track-select"><input type="checkbox" data-track-select data-uri="${esc(uri)}" data-position="${position}" aria-label="选择 ${esc(item.Title || item.Name || "曲目")}"><span></span></label>` : "";
    const action = queue
      ? `<button class="track-remove" data-remove-id="${esc(item.id)}" aria-label="从队列移除">${icon("close")}</button>`
      : playlist
        ? `<span class="track-order"><button data-move-from="${position}" data-move-to="${Math.max(0, position - 1)}" aria-label="上移" ${index === 0 ? "disabled" : ""}>↑</button><button data-move-from="${position}" data-move-to="${position + 1}" aria-label="下移" ${index === items.length - 1 ? "disabled" : ""}>↓</button></span>`
        : `<button class="track-add" data-add-uri="${esc(uri)}" aria-label="加入队列">${icon("plus")}</button>`;
    return `<article class="track-row${selectable ? " has-selection" : ""}${playlist ? " has-order" : ""}${Number(item.id) === model?.currentSongId ? " is-current" : ""}"${queue ? ` data-song-id="${esc(item.id ?? "")}"` : ""}>${selection}<button class="track-play" data-play-id="${esc(item.id ?? "")}" data-uri="${esc(uri)}" aria-label="播放 ${esc(item.Title || item.Name || "曲目")}">${icon("play-filled")}</button><span class="track-index">${String(index + 1).padStart(2, "0")}</span><div><b>${esc(item.Title || item.Name || "未知曲目")}</b><small>${esc([item.Artist || item.AlbumArtist, item.Album].filter(Boolean).join(" · "))}</small></div><time>${time(item.Duration || item.duration || 0)}</time>${action}</article>`;
  }).join("")}</div>` : empty(title, "换一个分类或搜索词试试");
  $$('[data-play-id]', $("#playerContent")).forEach(button => button.onclick = () => run(() => button.dataset.playId ? mpd.actions.playSong(button.dataset.playId) : mpd.actions.replaceUris([button.dataset.uri])));
  $$('[data-add-uri]', $("#playerContent")).forEach(button => button.onclick = () => run(() => mpd.actions.appendUris([button.dataset.addUri])));
  $$('[data-remove-id]', $("#playerContent")).forEach(button => button.onclick = () => run(() => mpd.actions.removeQueue([button.dataset.removeId])).then(() => renderView("queue")));
  if (playlist) $$('[data-move-from]', $("#playerContent")).forEach(button => button.onclick = async () => { if (await run(() => mpd.actions.movePlaylistPosition(playlist, button.dataset.moveFrom, button.dataset.moveTo), false)) await showPlaylist(playlist); });
}

async function renderSearchResults(query) {
  const [items, lists] = await Promise.all([mpd.tracks(query), mpd.playlists()]);
  renderTracks(items, "没有匹配曲目", { selectable: true });
  if (items.length) installSelectionBar(lists);
}

function installSelectionBar(lists, playlist = "") {
  const bar = document.createElement("section");
  bar.className = "selection-bar";
  bar.innerHTML = `<label><input type="checkbox" data-select-all><span>全选</span></label><b data-selection-count>已选 0 首</b>${playlist ? `<button data-remove-selected disabled>${icon("close")}移出歌单</button>` : `<select data-playlist-target aria-label="选择已有歌单"><option value="">选择已有歌单</option>${lists.map(item => `<option value="${esc(item.uri || item.Name)}">${esc(item.Name || item.uri)}</option>`).join("")}</select><button data-add-existing disabled>加入歌单</button><button data-add-new disabled>${icon("plus")}新建歌单</button>`}`;
  $("#playerContent").prepend(bar);
  const boxes = $$('[data-track-select]', $("#playerContent"));
  const selected = () => boxes.filter(box => box.checked);
  const sync = () => {
    const count = selected().length;
    $("[data-selection-count]", bar).textContent = `已选 ${count} 首`;
    $$('button', bar).forEach(button => { button.disabled = !count; });
    const addExisting = $("[data-add-existing]", bar), target = $("[data-playlist-target]", bar);
    if (addExisting) addExisting.disabled = !count || !target.value;
    $("[data-select-all]", bar).checked = count > 0 && count === boxes.length;
    $("[data-select-all]", bar).indeterminate = count > 0 && count < boxes.length;
  };
  boxes.forEach(box => box.onchange = sync);
  $("[data-select-all]", bar).onchange = event => { boxes.forEach(box => { box.checked = event.target.checked; }); sync(); };
  if (playlist) {
    $("[data-remove-selected]", bar).onclick = async () => { const positions = selected().map(box => box.dataset.position); if (await run(() => mpd.actions.removePlaylistPositions(playlist, positions))) await showPlaylist(playlist); };
    return;
  }
  $("[data-playlist-target]", bar).onchange = event => { $("[data-add-existing]", bar).disabled = !selected().length || !event.target.value; };
  $("[data-add-existing]", bar).onclick = async () => { const target = $("[data-playlist-target]", bar).value; if (target && await addSelectionToPlaylist(target, selected())) sync(); };
  $("[data-add-new]", bar).onclick = async () => { const name = await askPlaylistName("新建歌单", ""); if (name && await addSelectionToPlaylist(name, selected())) sync(); };
}

async function addSelectionToPlaylist(plist, boxes) {
  const uris = boxes.map(box => box.dataset.uri).filter(Boolean);
  if (!uris.length) return false;
  const ok = await run(() => mpd.actions.appendPlaylistUris(plist, uris));
  if (ok) boxes.forEach(box => { box.checked = false; });
  return ok;
}

async function renderPlaylists() {
  $(".player-content-head .play-all")?.remove();
  const lists = await mpd.playlists();
  $("#playerContent").innerHTML = lists.length ? `<div class="playlist-grid">${lists.map(item => { const plist = item.uri || item.Name || ""; const name = item.Name || item.Playlist || plist; return `<article class="playlist-card"><button data-plist="${esc(plist)}"><span>${icon("playlist")}</span><div><b>${esc(name || "未命名歌单")}</b><small>打开歌单</small></div>${icon("chevron-right")}</button></article>`; }).join("")}</div>` : empty("还没有歌单", "从曲库搜索歌曲后可创建第一个歌单");
  $$('[data-plist]', $("#playerContent")).forEach(button => button.onclick = async () => {
    if (!button.dataset.plist) return toast("歌单名称无效", true);
    try { await showPlaylist(button.dataset.plist); } catch (error) { toast(error.message, true, 5000); }
  });
}

async function showPlaylist(plist) {
  const tracks = await mpd.playlistTracks(plist);
  renderTracks(tracks, "歌单为空", { selectable: true, playlist: plist });
  const head = document.createElement("section");
  head.className = "playlist-edit-head";
  head.innerHTML = `<button data-playlist-back>${icon("collapse")}返回歌单</button><strong>${esc(plist)}</strong><span><button data-playlist-rename>${icon("edit")}重命名</button><button data-playlist-delete>${icon("close")}删除</button></span>`;
  if (tracks.length) installSelectionBar([], plist);
  $("#playerContent").prepend(head);
  addPlayAll(plist, true);
  $("[data-playlist-back]", head).onclick = () => renderView("playlists");
  $("[data-playlist-rename]", head).onclick = async () => {
    const name = await askPlaylistName("重命名歌单", plist);
    if (name && name !== plist && await run(() => mpd.actions.renamePlaylist(plist, name))) await showPlaylist(name);
  };
  $("[data-playlist-delete]", head).onclick = async () => {
    if (!await askConfirm("删除歌单？", `将通过 myMPD 删除“${plist}”，音乐文件不会被删除。`)) return;
    if (await run(() => mpd.actions.removePlaylists([plist]))) await renderView("playlists");
  };
}

async function renderRadios(query) {
  const radios = await mpd.radios(query);
  $("#playerContent").innerHTML = radios.length ? `<div class="radio-grid">${radios.map(item => `<button class="radio-card" data-radio="${esc(item.StreamUri)}"><img src="${esc(mpd.coverFor(item, true))}" alt="" loading="lazy"><span class="radio-live"><i></i>LIVE</span><div><b>${esc(item.Name)}</b><small>${esc([item.Country, ...(item.Genres || [])].filter(Boolean).join(" · ") || "网络电台")}</small></div>${icon("play-filled")}</button>`).join("")}</div>` : empty("没有匹配电台", "检查 myMPD 网络电台收藏");
  installArtworkFallback(".radio-card img", "/art/radio-placeholder.svg");
  $$('[data-radio]', $("#playerContent")).forEach(button => button.onclick = () => run(() => mpd.actions.replacePlaylist(mpd.radioPlaylistUri(button.dataset.radio))));
}

function addPlayAll(value, playlist) { const head = $(".player-content-head"); head.querySelector(".play-all")?.remove(); const button = document.createElement("button"); button.className = "play-all"; button.innerHTML = `${icon("play-filled")}播放全部`; button.onclick = () => run(() => playlist ? mpd.actions.replacePlaylist(value) : mpd.actions.replaceUris(value)); head.append(button); }
async function playerAction(action) { const fn = action === "toggle" ? (model?.state === "play" ? mpd.actions.pause : mpd.actions.play) : mpd.actions[action]; if (fn) await run(fn); }
function currentPlaybackMode() {
  if (model?.random) return "shuffle";
  if (model?.single === "1") return "repeat-one";
  if (model?.repeat) return "repeat-all";
  return "order";
}
function syncPlaybackMode() {
  const modes = {
    order: ["顺序播放", "queue"],
    "repeat-all": ["列表循环", "repeat"],
    "repeat-one": ["单曲循环", "repeat-one"],
    shuffle: ["随机循环", "shuffle"],
  };
  const mode = currentPlaybackMode();
  const [label, iconName] = modes[mode];
  const button = $("#playerModeButton");
  if (button.dataset.mode === mode) return;
  button.dataset.mode = mode;
  button.setAttribute("aria-label", `${label}，点击切换`);
  button.title = label;
  setHref($("#playerModeIcon"), `/icons.svg#icon-${iconName}`);
}
async function cyclePlaybackMode() {
  const order = ["order", "repeat-all", "repeat-one", "shuffle"];
  const next = order[(order.indexOf(currentPlaybackMode()) + 1) % order.length];
  const options = {
    order: { repeat: false, random: false, single: "0" },
    "repeat-all": { repeat: true, random: false, single: "0" },
    "repeat-one": { repeat: true, random: false, single: "1" },
    shuffle: { repeat: true, random: true, single: "0" },
  };
  await run(() => mpd.actions.playbackMode(options[next]));
}
async function run(fn) { try { await fn(); await refreshPlayer(); return true; } catch (error) { toast(error.message, true, 5000); return false; } }
function scheduleRefresh() { clearTimeout(scheduleRefresh.timer); scheduleRefresh.timer = setTimeout(async () => { try { await refreshPlayer(); if (activeView === "queue") await refreshQueue(); } catch (error) { setEngineState(false); } }, 180); }
function startClock() { clearInterval(refreshTimer); refreshTimer = setInterval(() => { if (!model) return; if (model.state === "play") model.elapsed = Math.min(model.duration || Infinity, model.elapsed + .25); if (!isRangeInteracting($("#playerSeek"))) { $("#playerSeek").value = model.elapsed; syncThumbDragRange($("#playerSeek")); } $("#playerElapsed").textContent = time(model.elapsed); }, 250); }
function setEngineState(ok) { const node = $("#playerEngineState"); if (node.dataset.online === String(ok)) return; node.dataset.online = String(ok); node.classList.toggle("online", ok); node.querySelector("span").textContent = ok ? "音乐引擎在线" : "正在重连"; }
function setText(node, value) { if (node.textContent !== String(value)) node.textContent = value; }
function setHref(node, value) { if (node.getAttribute("href") !== value) node.setAttribute("href", value); }
function isRangeInteracting(input) { return document.activeElement === input || input.dataset.dragging === "true"; }
function empty(title, copy, error = false) { return `<div class="player-empty${error ? " is-error" : ""}"><img src="/art/empty-state.svg" alt=""><h3>${esc(title)}</h3><p>${esc(copy)}</p></div>`; }
function time(seconds) { const n = Math.max(0, Math.floor(Number(seconds) || 0)); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`; }
function installArtworkFallback(selector, fallback) { $$(selector, $("#playerContent")).forEach(image => image.addEventListener("error", () => { if (!image.src.endsWith(fallback)) image.src = fallback; }, { once: true })); }
function askPlaylistName(title, value) {
  return new Promise(resolve => {
    const dialog = document.createElement("dialog");
    dialog.className = "modal playlist-name-dialog";
    dialog.innerHTML = `<form class="dialog-card compact-dialog"><h2>${esc(title)}</h2><label><span>歌单名称</span><input name="playlistName" maxlength="200" value="${esc(value)}" required autocomplete="off"></label><div class="dialog-actions"><button type="button" class="secondary" data-cancel>取消</button><button class="accent-btn">确定</button></div></form>`;
    document.body.append(dialog);
    const finish = result => { dialog.close(); dialog.remove(); resolve(result); };
    $("[data-cancel]", dialog).onclick = () => finish("");
    $("form", dialog).onsubmit = event => { event.preventDefault(); finish(event.currentTarget.elements.playlistName.value.trim()); };
    dialog.addEventListener("cancel", event => { event.preventDefault(); finish(""); }, { once: true });
    dialog.showModal();
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
    const samples = Array.from({ length: Math.ceil(pixels.length / 16) }, (_, index) => index * 16)
      .filter(index => pixels[index + 3] >= 150);
    if (!samples.length) return;
    const totals = samples.reduce((sum, index) => [sum[0] + pixels[index], sum[1] + pixels[index + 1], sum[2] + pixels[index + 2]], [0, 0, 0]);
    document.documentElement.style.setProperty("--player-accent", totals.map(value => Math.round(value / samples.length)).join(" "));
  } catch {
    // Cross-origin station artwork may not expose pixels; the default accent remains readable.
  }
}
