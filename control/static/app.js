import { post, request } from "./js/api.js";
import { state } from "./js/store.js";
import { $, $$, closeDialog, openDialog, toast } from "./js/ui.js";
import { renderZones } from "./js/zones.js";

let pollTimer;
let bootstrapped = false;

async function start() {
  initTheme();
  initEvents();
  setPlayerLinks();
  await checkAuth();
}

function setPlayerLinks() {
  const url = `${location.protocol}//${location.hostname}:1782/`;
  ["#mympdLink", "#openPlayerButton", "#settingsPlayerLink"].forEach(selector => { $(selector).href = url; });
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
      return;
    }
    closeDialog("#loginDialog");
    bootstrapped = true;
    await refreshState();
    startPolling();
  } catch (error) {
    toast(error.message, true);
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
  } catch (error) {
    if (error.status === 401) return;
    $("#healthLamp").classList.remove("ok");
    $("#healthText").textContent = "连接中断";
  }
}

function navigate(route) {
  $$('[data-route]').forEach(button => button.classList.toggle("active", button.dataset.route === route));
  $$('[data-page]').forEach(page => page.classList.toggle("active", page.dataset.page === route));
  history.replaceState(null, "", `#${route}`);
}

function initEvents() {
  document.addEventListener("auth-required", openLogin);
  document.addEventListener("state-refresh", refreshState);
  document.addEventListener("click", event => {
    const route = event.target.closest("[data-route]");
    if (route) navigate(route.dataset.route);
    const close = event.target.closest("[data-close-dialog]");
    if (close) closeDialog(close.closest("dialog"));
  });
  $("#loginForm").onsubmit = login;
  $("#refreshRooms").onclick = refreshState;
  $("#logoutButton").onclick = logout;
  $("#themeSelect").onchange = event => setTheme(event.target.value);
  navigate(location.hash.slice(1) === "settings" ? "settings" : "devices");
}

async function logout() {
  try { await post("/api/logout", {}); } catch {}
  state.auth.authenticated = false;
  bootstrapped = false;
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
