import { post } from "./api.js";
import { state } from "./store.js";
import { $, $$, askConfirm, esc, icon, toast } from "./ui.js";

let renderSignature = "";

export function renderZones(force = false) {
  $("#zoneCount").textContent = state.zones.length;
  renderBatchSources();

  const signature = JSON.stringify({ zones: state.zones, sources: state.sources, song: state.player.song });
  if (!force && signature === renderSignature) return;
  renderSignature = signature;
  const list = $("#zoneList");
  const expanded = new Set($$(".zone-card details[open]", list).map(node => node.closest(".zone-card").dataset.zoneId));
  list.replaceChildren();
  state.zones.forEach(zone => list.append(zoneCard(zone, expanded.has(zone.id))));
  if (!list.children.length) list.innerHTML = '<p class="empty">未发现播放房间</p>';
}

function renderBatchSources() {
  const list = $("#allSourceList");
  const signature = state.sources.map(source => `${source.id}:${source.status}`).join("|");
  if (list.dataset.signature === signature) return;
  list.dataset.signature = signature;
  list.innerHTML = state.sources.map(source => `<button data-all-source="${esc(source.id)}"><i></i>${esc(source.name)}</button>`).join("");
  $$('[data-all-source]', list).forEach(button => {
    button.onclick = async () => {
      const streamId = button.dataset.allSource;
      if (!await askConfirm("切换全部房间", `将所有房间切换到“${streamId}”？`)) return;
      await mutate("/api/snapcast/all-stream", { streamId });
    };
  });
}

function zoneCard(zone, expanded) {
  const card = document.createElement("article");
  card.className = "zone-card";
  card.dataset.zoneId = zone.id;
  const song = zone.sourceType === "mpd" ? state.player.song || {} : {};
  const now = zone.sourceType === "airplay" ? "AirPlay 外部音频" : song.title || "等待播放";
  const meta = zone.sourceType === "airplay" ? "由发送设备控制" : [song.artist, song.album].filter(Boolean).join(" · ") || "本地播放器";
  card.innerHTML = `<header class="zone-head"><div><span class="room-orb"></span><div><small>ZONE</small><h2>${esc(zone.name)}</h2></div></div><span class="zone-online">${zone.connectedCount}/${zone.clients.length} 在线</span></header>
    <div class="zone-now"><small>${esc(zone.source?.name || "UNKNOWN")} · ${zone.source?.status === "playing" ? "正在播放" : "等待音频"}</small><b>${esc(now)}</b><span>${esc(meta)}</span></div>
    <label class="group-volume"><span>${icon("volume")}<b>房间音量</b></span><input type="range" min="0" max="100" value="${zone.volume}"><output>${zone.volume}</output></label>
    <div class="zone-sources" aria-label="${esc(zone.name)}音源">${state.sources.map(source => `<button class="${zone.streamId === source.id ? "active" : ""}" data-zone-source="${esc(source.id)}"><i></i>${esc(source.name)}</button>`).join("")}</div>
    <details class="zone-devices" ${expanded ? "open" : ""}><summary><span>${icon("speaker")}设备与延迟</span><span>${zone.clients.length} 台 ${icon("expand")}</span></summary><div class="client-list"></div></details>`;

  const groupVolume = $(".group-volume input", card);
  const groupOutput = $(".group-volume output", card);
  groupVolume.oninput = () => { groupOutput.value = groupVolume.value; };
  groupVolume.onchange = () => mutate("/api/snapcast/group-volume", { groupId: zone.id, percent: Number(groupVolume.value), muted: false }, true);
  $$('[data-zone-source]', card).forEach(button => {
    button.onclick = () => mutate("/api/snapcast/stream", { groupId: zone.id, streamId: button.dataset.zoneSource });
  });
  const clients = $(".client-list", card);
  zone.clients.forEach(client => clients.append(clientRow(client)));
  return card;
}

function clientRow(client) {
  const row = document.createElement("section");
  row.className = "client-row";
  row.innerHTML = `<header><div><span class="dot ${client.connected ? "" : "off"}"></span><b>${esc(client.name)}</b><small>${esc(client.ip)} · ${client.connected ? "在线" : "离线"}</small></div><button class="icon-btn mute" aria-label="${client.muted ? "取消静音" : "静音"}">${icon(client.muted ? "mute" : "volume")}</button></header>
    <label class="client-volume"><span>音量</span><input type="range" min="0" max="100" value="${client.volume}"><output>${client.volume}</output></label>
    <div class="latency-control"><div><span>延迟补偿 · 向右加快</span><output>${client.latency} ms</output></div><input class="latency-range" type="range" min="-500" max="500" step="10" dir="rtl" value="${Math.max(-500, Math.min(500, client.latency))}"><footer><button data-step="10" aria-label="声音减慢">＋</button><button data-zero aria-label="延迟归零">${icon("reset")}</button><label><input class="latency-number" type="number" min="-1000" max="5000" step="10" value="${client.latency}"><span>ms</span></label><button data-step="-10" aria-label="声音加快">−</button></footer></div>`;
  const volume = $(".client-volume input", row), volumeOutput = $(".client-volume output", row);
  volume.oninput = () => { volumeOutput.value = volume.value; };
  volume.onchange = () => mutate("/api/snapcast/volume", { clientId: client.id, percent: Number(volume.value), muted: false }, true);
  $(".mute", row).onclick = () => mutate("/api/snapcast/volume", { clientId: client.id, percent: client.volume, muted: !client.muted }, true);
  const range = $(".latency-range", row), number = $(".latency-number", row), output = $(".latency-control>div output", row);
  const setLatency = value => {
    const normalized = Math.max(-1000, Math.min(5000, Math.round(Number(value) / 10) * 10));
    number.value = normalized;
    range.value = Math.max(-500, Math.min(500, normalized));
    output.value = `${normalized} ms`;
    mutate("/api/snapcast/latency", { clientId: client.id, latency: normalized }, true);
  };
  range.oninput = () => { number.value = range.value; output.value = `${range.value} ms`; };
  range.onchange = () => setLatency(range.value);
  number.onchange = () => setLatency(number.value);
  $$('[data-step]', row).forEach(button => { button.onclick = () => setLatency(Number(number.value) + Number(button.dataset.step)); });
  $("[data-zero]", row).onclick = () => setLatency(0);
  return row;
}

async function mutate(url, payload, quiet = false) {
  try {
    await post(url, payload);
    document.dispatchEvent(new CustomEvent("state-refresh"));
    if (!quiet) toast("已更新");
  } catch (error) {
    toast(error.message, true);
  }
}
