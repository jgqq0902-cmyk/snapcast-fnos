export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const icon = name => `<svg aria-hidden="true"><use href="/icons.svg#icon-${name}"/></svg>`;
export const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);

export function installTouchSafeRange(input, label = "调节滑轨") {
  if (!input || input.closest(".touch-range-shell")) return;
  const shell = document.createElement("span");
  shell.className = "touch-range-shell";
  input.before(shell);
  shell.append(input);
  const unlock = document.createElement("button");
  unlock.type = "button";
  unlock.className = "touch-range-unlock";
  unlock.setAttribute("aria-label", label);
  unlock.setAttribute("aria-pressed", "false");
  unlock.innerHTML = icon("edit");
  shell.append(unlock);
  const lock = () => {
    shell.classList.remove("is-unlocked");
    unlock.setAttribute("aria-pressed", "false");
  };
  if (matchMedia("(max-width: 700px) and (pointer: coarse)").matches) lock();
  unlock.onclick = () => {
    const unlocked = shell.classList.toggle("is-unlocked");
    unlock.setAttribute("aria-pressed", String(unlocked));
    if (unlocked) input.focus({ preventScroll: true });
  };
  input.addEventListener("change", lock);
  input.addEventListener("blur", () => setTimeout(lock, 120));
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
