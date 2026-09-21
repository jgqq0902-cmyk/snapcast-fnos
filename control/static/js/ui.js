export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const icon = name => `<svg aria-hidden="true"><use href="/icons.svg#icon-${name}"/></svg>`;
export const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
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
