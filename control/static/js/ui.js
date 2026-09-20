export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const icon = name => `<svg aria-hidden="true"><use href="/icons.svg#icon-${name}"/></svg>`;
export const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
export const clock = value => {
  const seconds = Math.max(0, Number(value) || 0);
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
};
export const artUrl = uri => uri ? `/api/player/art?uri=${encodeURIComponent(uri)}` : "";

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

export function setArtwork(container, uri, title = "", onload = null) {
  container.replaceChildren();
  if (!uri) {
    const fallback = document.createElement("span");
    fallback.textContent = "SR";
    container.append(fallback);
    return;
  }
  const image = document.createElement("img");
  image.alt = title;
  image.src = artUrl(uri);
  image.addEventListener("error", () => image.remove(), { once: true });
  if (onload) image.addEventListener("load", () => onload(image), { once: true });
  container.append(image);
}

export function askText(title, initial = "") {
  return new Promise(resolve => {
    const dialog = $("#inputDialog");
    $("#inputTitle").textContent = title;
    $("#inputValue").value = initial;
    $("#inputForm").onsubmit = event => {
      event.preventDefault();
      const value = $("#inputValue").value.trim();
      if (!value) return;
      dialog.close();
      resolve(value);
    };
    dialog.addEventListener("close", () => resolve(""), { once: true });
    openDialog(dialog);
    $("#inputValue").focus();
  });
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
