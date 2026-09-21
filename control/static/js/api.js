export class ApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export async function request(url, options = {}) {
  const response = await fetch(url, { credentials: "same-origin", ...options });
  const type = response.headers.get("content-type") || "";
  const data = type.includes("json") ? await response.json() : await response.text();
  if (response.status === 401 && url !== "/api/login") {
    document.dispatchEvent(new CustomEvent("auth-required"));
  }
  if (!response.ok || data?.ok === false) {
    throw new ApiError(data?.error || `HTTP ${response.status}`, response.status, typeof data === "object" ? data : null);
  }
  return data;
}

export function post(url, data) {
  return request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
