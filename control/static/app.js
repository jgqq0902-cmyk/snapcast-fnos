import { post, request } from "./js/api.js";
import { state } from "./js/store.js";
import { $, $$, closeDialog, openDialog, toast } from "./js/ui.js";
import { renderZones } from "./js/zones.js?v=20260925-compact";
import { activatePlayer, resetPlayer } from "./js/player.js?v=20260925-compact";

let pollTimer;
let bootstrapped = false;

async function start() {
  initTheme();
  initEvents();
  await checkAuth();
}

async function checkAuth() {
  try {
    state.auth = await request("/api/auth");
    $("#loginUsername").value = state.auth.username || "admin";
    $("#accountState").textContent = state.auth.enabled ? `已启用认证 · ${state.auth.username || "admin"}` : "可信家庭 LAN 模式 · 未启用认证";
    $("#logoutButton").hidden = !state.auth.enabled;
    if (state.auth.enabled && (!state.auth.configured || !state.auth.authenticated)) {
      if (!state.auth.configured) $("#loginHint").textContent = "服务端尚未设置 CONTROL_PASSWORD，请先完成部署配置。";
      openLogin();
      return false;
    }
    closeDialog("#loginDialog");
    bootstrapped = true;
    await refreshState();
    await activatePlayer();
    startPolling();
    return true;
  } catch (error) {
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
  state.player = { state: "stop", song: {}, capabilities: {} };
  renderZones(true);
  $("#deviceCount").textContent = "0";
  $("#devicePanelHost").innerHTML = `<section class="state-panel"><svg class="state-mark" aria-hidden="true"><use href="/icons.svg#icon-speaker"/></svg><h2>需要重新登录</h2><p>${message}</p></section>`;
  $("#dashboard").setAttribute("aria-busy", "false");
  resetPlayer();
}

function showConnectionError(message) {
  $("#devicePanelHost").innerHTML = `<section class="state-panel is-error"><svg class="state-mark" aria-hidden="true"><use href="/icons.svg#icon-network"/></svg><h2>网关连接中断</h2><p>${message || "无法读取设备状态，请检查网关服务和网络连接。"}</p><div class="state-actions"><button class="secondary-btn" data-retry-state>重新连接</button></div></section>`;
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
    state.player = data.player || state.player;
    state.playerSyncedAt = performance.now();
    state.sources = data.sources || data.snapcast?.streams || [];
    state.zones = data.zones || data.snapcast?.groups || [];
    state.mainGroup = data.mainGroup || data.snapcast?.mainGroup || null;
    state.system = { ...state.system, ...(data.system || {}), healthy: !data.errors?.length };
    $("#dashboard").setAttribute("aria-busy", "false");
    $("#healthLamp").classList.toggle("ok", state.system.healthy);
    $("#healthText").textContent = state.system.healthy ? "服务在线" : "部分异常";
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
  document.addEventListener("auth-required", () => {
    if (!state.auth.authenticated && !bootstrapped) return openLogin();
    state.auth.authenticated = false;
    bootstrapped = false;
    clearInterval(pollTimer);
    clearPrivateState();
    openLogin();
  });
  document.addEventListener("state-refresh", refreshState);
  document.addEventListener("click", event => {
    const close = event.target.closest("[data-close-dialog]");
    if (close) closeDialog(close.closest("dialog"));
  });
  $("#loginForm").onsubmit = login;
  $("#loginDialog").addEventListener("cancel", event => event.preventDefault());
  $("#loginDialog").addEventListener("close", () => {
    if (state.auth.enabled && !state.auth.authenticated) queueMicrotask(openLogin);
  });
  $("#refreshRooms").onclick = refreshState;
  $("#logoutButton").onclick = logout;
}

async function logout() {
  try { await post("/api/logout", {}); } catch {}
  state.auth.authenticated = false;
  bootstrapped = false;
  clearInterval(pollTimer);
  clearPrivateState("已安全退出，设备与播放状态已从页面清除。");
  openLogin();
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(refreshState, 2000);
}

function initTheme() {
  document.documentElement.dataset.theme = "dark";
  updateThemeColor();
}

function updateThemeColor() {
  $("#themeColor").content = "#07100f";
}

document.addEventListener("visibilitychange", () => {
  clearInterval(pollTimer);
  if (!document.hidden && bootstrapped) { refreshState(); startPolling(); }
});

start();
