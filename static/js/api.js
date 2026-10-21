// Thin fetch wrapper. The session lives in an HttpOnly cookie, so no token is ever visible to page scripts.
export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

function messageFrom(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => (d && d.msg) || "Invalid input").join("; ");
  return "Something went wrong";
}

function withParams(path, params) {
  if (!params) return path;
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, v);
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}

function failure(res, data, path) {
  if (res.status === 401 && !path.startsWith("/auth/login")) window.dispatchEvent(new Event("tv:unauth"));
  return new ApiError(res.status, messageFrom(data && data.detail));
}

export async function api(path, { method = "GET", json, form, params } = {}) {
  const opts = { method, credentials: "same-origin", headers: {} };
  if (json !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(json); }
  if (form) opts.body = form;
  let res;
  try { res = await fetch(withParams(path, params), opts); }
  catch { throw new ApiError(0, "Cannot reach the server. Check your connection."); }
  let data = null;
  if ((res.headers.get("content-type") || "").includes("json")) data = await res.json().catch(() => null);
  if (!res.ok) throw failure(res, data, path);
  return data;
}

function filenameFrom(disposition) {
  if (!disposition) return null;
  const star = /filename\*=utf-8''([^;]+)/i.exec(disposition);
  if (star) { try { return decodeURIComponent(star[1]); } catch { /* fall through */ } }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1] : null;
}

// Fetches a file through fetch() so a refused request (revoked access, expired session) shows a message
// instead of navigating the browser to a JSON error page. Used for downloads AND in-browser previews,
// so both are the same audited, server-authorised download.
export async function fetchFile(path) {
  let res;
  try { res = await fetch(path, { credentials: "same-origin" }); }
  catch { throw new ApiError(0, "Cannot reach the server. Check your connection."); }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw failure(res, data, path);
  }
  return { blob: await res.blob(), name: filenameFrom(res.headers.get("content-disposition")) };
}

export async function downloadFile(path, fallbackName) {
  const { blob, name } = await fetchFile(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name || fallbackName || "download";
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
