export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const icon = name => `<svg aria-hidden="true"><use href="/icons.svg#icon-${name}"/></svg>`;
export const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);

export function installThumbDragRange(input) {
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
    shell.style.setProperty("--thumb-position", `calc(${fraction * 100}% + ${10 - fraction * 20}px)`);
  };
  let dragging = false, initialValue, pointerId;
  handle.addEventListener("pointerdown", event => {
    if (event.pointerType === "mouse" && !matchMedia("(pointer: coarse)").matches) return;
    if (dragging || input.disabled || input.closest("[inert]")) return;
    initialValue = input.value;
    pointerId = event.pointerId;
    dragging = true;
    input.dataset.dragging = "true";
    handle.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  handle.addEventListener("pointermove", event => {
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
  const finish = event => {
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
    if (event?.pointerId !== undefined && handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
  };
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
  handle.addEventListener("lostpointercapture", finish);
  input.addEventListener("input", sync);
  input.addEventListener("thumb-sync", sync);
  sync();
}

export function syncThumbDragRange(input) {
  input?.dispatchEvent(new Event("thumb-sync"));
}
let toastTimer;
export function toast(message, error = false, duration = 2800) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.className = "toast"; }, duration);
}

export function openDialog(selector) {
  const dialog = typeof selector === "string" ? $(selector) : selector;
  if (dialog && !dialog.open) dialog.showModal();
}

export function closeDialog(selector) {
  const dialog = typeof selector === "string" ? $(selector) : selector;
  if (dialog?.open) dialog.close();
}

export function askConfirm(title, message) {
  return new Promise(resolve => {
    const dialog = $("#confirmDialog");
    $("#confirmTitle").textContent = title;
    $("#confirmMessage").textContent = message;
    $("#confirmForm").onsubmit = event => {
      event.preventDefault();
      dialog.close();
      resolve(true);
    };
    dialog.addEventListener("close", () => resolve(false), { once: true });
    openDialog(dialog);
  });
}
