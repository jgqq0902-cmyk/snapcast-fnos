import { post, request } from "./js/api.js";
import { state } from "./js/store.js";
import { $, $$, askConfirm, closeDialog, openDialog, toast } from "./js/ui.js";
import { initGroups, renderGroupManager } from "./js/groups.js";
import { renderZones } from "./js/zones.js";

let pollTimer;
let bootstrapped = false;
let pendingRoute = "devices";

async function start() {
  initTheme();
  setPlayerLinks();
  initEvents();
  initGroups();
  if (await checkAuth()) navigate(pendingRoute);
}

function setPlayerLinks() {
  const url = new URL("/player/", location.href).href;
  ["#openPlayerWindow", "#settingsPlayerLink"].forEach(selector => { $(selector).href = url; });
  $("#mympdFrame").dataset.src = url;
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
    startPolling();
    return true;
  } catch (error) {
    toast(error.message, true);
    return false;
  }
}

function openLogin() {
  const dialog = $("#loginDialog");
  dialog.addEventListener("cancel", event => event.preventDefault(), { once: true });
  openDialog(dialog);
}

async function login(event) {
  event.preventDefault();
  try {
    await post("/api/login", { username: $("#loginUsername").value, password: $("#loginPassword").value });
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
    state.sources = data.sources || data.snapcast?.streams || [];
    state.zones = data.zones || data.snapcast?.groups || [];
    state.system = { ...state.system, ...(data.system || {}), healthy: !data.errors?.length };
    $("#healthLamp").classList.toggle("ok", state.system.healthy);
    $("#healthText").textContent = state.system.healthy ? "服务在线" : "部分异常";
    $("#gatewayName").textContent = state.system.hostname || "本机网关";
    renderZones();
    if ($("#groupsDialog").open) renderGroupManager();
  } catch (error) {
    if (error.status === 401) return;
    $("#healthLamp").classList.remove("ok");
    $("#healthText").textContent = "连接中断";
  }
}

function navigate(route) {
  if (!["devices", "player", "settings"].includes(route)) route = "devices";
  pendingRoute = route;
  $$('[data-route]').forEach(button => button.classList.toggle("active", button.dataset.route === route));
  $$('[data-page]').forEach(page => page.classList.toggle("active", page.dataset.page === route));
  document.body.classList.toggle("player-mode", route === "player");
  if (route === "player") loadPlayer();
  history.replaceState(null, "", `#${route}`);
}

function loadPlayer(force = false) {
  const frame = $("#mympdFrame");
  if (!bootstrapped || !state.auth.authenticated || !frame.dataset.src) return;
  if (force || !frame.hasAttribute("src")) {
    $("#playerPlaceholder").classList.remove("hidden");
    frame.src = frame.dataset.src;
  }
}

function initEvents() {
  document.addEventListener("auth-required", openLogin);
  document.addEventListener("state-refresh", refreshState);
  document.addEventListener("click", event => {
    const route = event.target.closest("[data-route]");
    if (route && bootstrapped) navigate(route.dataset.route);
    const close = event.target.closest("[data-close-dialog]");
    if (close) closeDialog(close.closest("dialog"));
  });
  $("#loginForm").onsubmit = login;
  $("#refreshRooms").onclick = refreshState;
  $("#reloadPlayer").onclick = () => loadPlayer(true);
  $("#mympdFrame").onload = () => $("#playerPlaceholder").classList.add("hidden");
  $("#stopAllSources").onclick = stopAllSources;
  $("#logoutButton").onclick = logout;
  $("#themeSelect").onchange = event => setTheme(event.target.value);
  pendingRoute = ["player", "settings"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "devices";
}

async function stopAllSources() {
  const confirmed = await askConfirm("立即停止所有音源？", "将停止本地与 DLNA 播放并断开当前 AirPlay 会话。MPD 队列和播放位置会保留，设备音量、静音、延迟和分组不会改变。");
  if (!confirmed) return;
  const button = $("#stopAllSources");
  const content = button.innerHTML;
  button.disabled = true;
  button.textContent = "正在停止…";
  try {
    const response = await post("/api/sources/stop-all", {});
    const errors = response.result?.errors || [];
    toast(errors.length ? `部分音源停止失败：${errors.join("；")}` : "所有音源已停止", Boolean(errors.length), errors.length ? 6000 : 2800);
    await refreshState();
  } catch (error) {
    toast(error.message, true, 5000);
  } finally {
    button.innerHTML = content;
    button.disabled = false;
  }
}

async function logout() {
  try { await post("/api/logout", {}); } catch {}
  state.auth.authenticated = false;
  bootstrapped = false;
  $("#mympdFrame").removeAttribute("src");
  clearInterval(pollTimer);
  openLogin();
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(refreshState, 2000);
}

function initTheme() {
  setTheme(localStorage.getItem("snaproomTheme") || "system");
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", updateThemeColor);
}

function setTheme(value) {
  document.documentElement.dataset.theme = value;
  localStorage.setItem("snaproomTheme", value);
  if ($("#themeSelect")) $("#themeSelect").value = value;
  updateThemeColor();
}

function updateThemeColor() {
  const dark = document.documentElement.dataset.theme === "dark" || (document.documentElement.dataset.theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  $("#themeColor").content = dark ? "#171312" : "#f4eee6";
}

document.addEventListener("visibilitychange", () => {
  clearInterval(pollTimer);
  if (!document.hidden && bootstrapped) { refreshState(); startPolling(); }
});

start();
