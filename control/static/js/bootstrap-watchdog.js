(function () {
  "use strict";

  document.documentElement.dataset.consoleBoot = "loading";

  window.setTimeout(function () {
    var state = document.documentElement.dataset.consoleBoot;
    if (state === "ready" || state === "auth") return;

    var health = document.getElementById("healthText");
    var engine = document.querySelector("#playerEngineState span");
    var player = document.getElementById("playerContent");
    var devices = document.getElementById("devicePanelHost");
    var dashboard = document.getElementById("dashboard");
    var retry = '<button class="secondary-btn" data-boot-reload>重新载入</button>';

    if (health) health.textContent = "页面加载失败";
    if (engine) engine.textContent = "启动失败";
    if (player) player.innerHTML = '<div class="player-loading"><b>控制台脚本未能启动</b><small>请重新载入以更新本地缓存</small>' + retry + "</div>";
    if (devices) devices.innerHTML = '<section class="state-panel is-error"><svg class="state-mark" aria-hidden="true"><use href="/icons.svg#icon-network"/></svg><h2>控制台加载失败</h2><p>浏览器可能仍在使用旧版页面资源。</p>' + retry + "</section>";
    if (dashboard) dashboard.setAttribute("aria-busy", "false");

    Array.prototype.forEach.call(document.querySelectorAll("[data-boot-reload]"), function (button) {
      button.addEventListener("click", function () {
        var url = new URL(window.location.href);
        url.searchParams.set("reload", String(Date.now()));
        window.location.replace(url.toString());
      });
    });
  }, 10000);
}());
