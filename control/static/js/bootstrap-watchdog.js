(function () {
  "use strict";

  function report(stage) {
    var image = new Image();
    image.src = "/art/compat-probe.svg?stage=" + encodeURIComponent(stage) + "&t=" + Date.now();
  }

  window.__snapProbe = report;
  report("watchdog-start");
  document.documentElement.dataset.consoleBoot = "loading";
  var bootError = "";
  window.addEventListener("error", function (event) {
    if (event.message) bootError = event.message;
    else if (event.target && event.target.src) bootError = "无法加载 " + event.target.src.split("/").pop();
  }, true);

  window.setTimeout(function () {
    var state = document.documentElement.dataset.consoleBoot;
    if (state === "ready" || state === "auth") return;
    report("watchdog-timeout-" + (state || "unset"));

    var health = document.getElementById("healthText");
    var engine = document.querySelector("#playerEngineState span");
    var player = document.getElementById("playerContent");
    var devices = document.getElementById("devicePanelHost");
    var dashboard = document.getElementById("dashboard");
    var retry = '<button class="secondary-btn" data-boot-reload>重新载入</button>';

    if (health) health.textContent = "页面加载失败";
    if (engine) engine.textContent = "启动失败";
    var detail = bootError ? "错误：" + bootError : "浏览器可能不支持当前页面脚本";
    if (player) player.innerHTML = '<div class="player-loading"><b>控制台脚本未能启动</b><small data-boot-error></small>' + retry + "</div>";
    if (devices) devices.innerHTML = '<section class="state-panel is-error"><svg class="state-mark" aria-hidden="true"><use href="/icons.svg#icon-network"/></svg><h2>控制台加载失败</h2><p data-boot-error></p>' + retry + "</section>";
    if (dashboard) dashboard.setAttribute("aria-busy", "false");
    Array.prototype.forEach.call(document.querySelectorAll("[data-boot-error]"), function (node) {
      node.textContent = detail;
    });

    Array.prototype.forEach.call(document.querySelectorAll("[data-boot-reload]"), function (button) {
      button.addEventListener("click", function () {
        var url = new URL(window.location.href);
        url.searchParams.set("reload", String(Date.now()));
        window.location.replace(url.toString());
      });
    });
  }, 10000);
}());
