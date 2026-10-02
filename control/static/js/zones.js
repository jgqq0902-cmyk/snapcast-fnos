import { post } from "./api.js?v=20261002-ios2";
import { state } from "./store.js?v=20261002-ios2";
import { $, $$, clearChildren, closeDialog, esc, icon, installThumbDragRange, openDialog, syncThumbDragRange, toast } from "./ui.js?v=20261002-ios2";

let renderSignature = "";

export function renderZones(force = false) {
  const clients = (state.mainGroup && state.mainGroup.clients) || [];
  $("#deviceCount").textContent = clients.length;
  const signature = JSON.stringify({
    groupId: (state.mainGroup && state.mainGroup.id) || "",
    clients: clients.map(client => ({
      id: client.id,
      name: client.name,
      connected: Boolean(client.connected),
      active: Boolean(client.participating !== null && client.participating !== undefined ? client.participating : (client.active !== null && client.active !== undefined ? client.active : !client.muted)),
      audible: Boolean(client.audible),
      volume: Number(client.volume),
      latency: Number(client.latency),
    })),
  });
  if (!force && signature === renderSignature) return;
  if ($("#devicePanelHost dialog[open]")) return;
  renderSignature = signature;
  const host = $("#devicePanelHost");
  clearChildren(host);
  if (!state.mainGroup) {
    host.innerHTML = `<section class="state-panel"><svg class="state-mark" aria-hidden="true"><use href="/icons.svg#icon-speaker"/></svg><h2>暂未发现设备</h2><div class="state-actions"><button class="secondary-btn" data-empty-refresh>刷新</button></div></section>`;
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
  panel.innerHTML = `<div class="compact-client-list"></div>`;
  const list = $(".compact-client-list", panel);
  clients.forEach((client, index) => list.append(clientCard(client, index)));
  return panel;
}

function clientCard(client, index) {
  const active = client.participating !== null && client.participating !== undefined ? client.participating : (client.active !== null && client.active !== undefined ? client.active : !client.muted);
  const card = document.createElement("article");
  const variant = speakerVariant(client.name, client.id, index);
  card.className = `speaker-unit${client.connected ? "" : " is-offline"}${active ? " is-active" : " is-inactive"}${client.audible ? " is-audible" : ""}`;
  card.innerHTML = `<button class="speaker-toggle" aria-label="${esc(client.name)}${active ? "关闭" : "激活"}" ${client.connected ? "" : "disabled"}><span class="speaker-visual ${variant}" aria-hidden="true"><i></i><i></i><i></i></span><strong>${esc(client.name)}</strong><span class="speaker-light" aria-hidden="true"></span></button>
    <button class="speaker-settings" aria-label="打开 ${esc(client.name)} 设置">${icon("settings")}</button>
    <div class="device-dialog modal" role="dialog" aria-modal="true" aria-label="${esc(client.name)} 设置"><form class="device-dialog-card">
      <header><div class="speaker-mini ${variant}" aria-hidden="true"><i></i></div><div class="device-identity"><span>设备名称</span><strong class="device-name-display">${esc(client.name)}</strong><label hidden><input class="device-name" maxlength="64" value="${esc(client.name)}" aria-label="设备名称"></label></div><button type="button" class="edit-device-name" aria-label="编辑设备名称">${icon("edit")}</button><button type="button" class="dialog-close" aria-label="关闭">${icon("close")}</button></header>
      <label class="device-volume-control"><span>${icon("volume")}</span><input aria-label="${esc(client.name)}音量" type="range" min="0" max="100" value="${client.volume}" ${client.connected && active ? "" : "disabled"}><output>${client.volume}</output></label>
      <section class="latency-control"><div><span>向右加快 · 向左减慢</span><output>${client.latency} ms</output></div><input class="latency-range" aria-label="${esc(client.name)}延迟" type="range" min="-500" max="500" step="10" dir="rtl" value="${Math.max(-500, Math.min(500, client.latency))}"><footer><button type="button" data-step="10" aria-label="声音减慢">＋</button><button type="button" data-zero aria-label="延迟归零">${icon("reset")}</button><label><input class="latency-number" type="number" min="-1000" max="5000" step="10" value="${client.latency}"><span>ms</span></label><button type="button" data-step="-10" aria-label="声音加快">−</button></footer></section>
      <button class="save-device-name" type="submit" hidden>保存名称</button>
    </form></div>`;
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
  $("form", dialog).onsubmit = async event => {
    event.preventDefault();
    const name = $(".device-name", dialog).value.trim();
    if (name && await mutate("/api/snapcast/client-name", { clientId: client.id, name }, true)) closeDialog(dialog);
  };
  const volume = $(".device-volume-control input", card), volumeOutput = $(".device-volume-control output", card);
  volume.oninput = () => { volumeOutput.value = volume.value; };
  volume.onchange = () => mutate("/api/snapcast/volume", { clientId: client.id, percent: Number(volume.value), muted: false }, true);
  const range = $(".latency-range", card), number = $(".latency-number", card), latencyOutput = $(".latency-control>div output", card);
  const setLatency = value => {
    if (String(value).trim() === "" || !Number.isFinite(Number(value))) { toast("请输入有效的延迟数值", true); return; }
    const normalized = Math.max(-1000, Math.min(5000, Math.round(Number(value) / 10) * 10));
    number.value = normalized; range.value = Math.max(-500, Math.min(500, normalized)); latencyOutput.value = `${normalized} ms`;
    syncThumbDragRange(range);
    mutate("/api/snapcast/latency", { clientId: client.id, latency: normalized }, true);
  };
  range.oninput = () => { number.value = range.value; latencyOutput.value = `${range.value} ms`; };
  range.onchange = () => setLatency(range.value);
  installThumbDragRange(volume);
  installThumbDragRange(range);
  number.onchange = () => setLatency(number.value);
  $$('[data-step]', card).forEach(button => { button.onclick = () => setLatency(Number(number.value) + Number(button.dataset.step)); });
  $("[data-zero]", card).onclick = () => setLatency(0);
  return card;
}

function speakerVariant(name, id, index) {
  const normalized = `${name} ${id}`.toLowerCase();
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
