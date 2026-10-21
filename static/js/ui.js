// DOM helpers. Everything is built with createElement and text nodes (no HTML-string APIs),
// so data from the server (names, emails, descriptions) can never be interpreted as markup.
import { ApiError } from "./api.js";
import { icon } from "./icons.js";

export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  let value;
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "value") { value = v; continue; }
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k in el) { try { el[k] = v; } catch { el.setAttribute(k, v); } }
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, kids);
  if (value !== undefined) el.value = value;      // after <option>s exist
  return el;
}

export function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

export function toast(message, kind = "info", ms = 4500) {
  const box = document.getElementById("toasts");
  const t = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  box.append(t);
  setTimeout(() => t.remove(), ms);
}

export const errMsg = (e) => (e instanceof ApiError ? e.message : "Unexpected error");

/* ---------- formatting ---------- */
const HAS_TZ = /([zZ]|[+-]\d\d:?\d\d)$/;
export function parseDate(s) { return new Date(HAS_TZ.test(s) ? s : `${s}Z`); }
export function fmtDate(s) { return s ? parseDate(s).toLocaleString() : "—"; }
export function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}
export const dayStart = (d) => (d ? new Date(`${d}T00:00:00`).toISOString() : "");
export const dayEnd = (d) => (d ? new Date(`${d}T23:59:59`).toISOString() : "");
export const shortId = (id) => (id ? `${id.slice(0, 8)}…` : "—");

/* ---------- small components ---------- */
export const badge = (text, kind = "") => h("span", { class: `badge ${kind}` }, text);
export const roleBadge = (r) => badge(r, { admin: "amber", owner: "blue", viewer: "" }[r] || "");
export const statusBadge = (s) => badge({ pending: "Pending approval", active: "Active", rejected: "Rejected", suspended: "Suspended" }[s] || s,
  { pending: "amber", active: "green", rejected: "red", suspended: "red" }[s] || "");
export const reviewBadge = (s) => badge({ pending: "Awaiting review", approved: "Approved", rejected: "Rejected" }[s] || s,
  { pending: "amber", approved: "green", rejected: "red" }[s] || "");
export const providerBadge = (u) => u.auth_provider === "google" ? badge("Google verified", "green")
  : u.email_verified ? badge("Email verified", "green") : badge("Email not verified", "amber");
export const accessBadge = (a) =>
  a === "owner" ? badge("Owner", "blue") : a === "edit" ? badge("Can edit", "green") : badge("Read only");
export const outcomeBadge = (o) => badge(o, o === "allowed" ? "green" : "red");
export const severityBadge = (s) =>
  badge(s, { critical: "critical", high: "red", medium: "amber", info: "blue" }[s] || "");

export function pageHeader(title, subtitle, ...actions) {
  return h("div", { class: "page-head" },
    h("div", { class: "titles" }, h("h1", null, title), subtitle ? h("p", null, subtitle) : null),
    h("div", { class: "actions" }, actions));
}
export const loading = (text = "Loading…") => h("div", { class: "loading" }, h("span", { class: "spinner" }), text);
export const empty = (title, text) => h("div", { class: "empty" }, h("div", { class: "big" }, title), text ? h("div", null, text) : null);
export const notice = (text, kind = "") => h("div", { class: `notice ${kind}`, role: "status" }, text);
export const card = (title, ...body) => h("section", { class: "card" }, title ? h("h2", null, title) : null, body);

export function table(headers, rows) {
  return h("div", { class: "table-wrap" }, h("table", null,
    h("thead", null, h("tr", null, headers.map((x) => h("th", null, x)))),
    h("tbody", null, rows.map((r) => h("tr", null, r.map((c) => h("td", null, c)))))));
}

export function field(label, input, help) {
  const id = `f_${Math.random().toString(36).slice(2, 9)}`;
  input.id = id;
  return h("div", { class: "field" }, h("label", { htmlFor: id }, label), input, help ? h("span", { class: "help" }, help) : null);
}

/* ---------- modals ---------- */
export function openModal({ title, content, wide = false }) {
  const previouslyFocused = document.activeElement;
  const backdrop = h("div", { class: "backdrop" });
  const close = () => {
    document.removeEventListener("keydown", onKey);
    backdrop.remove();
    if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const titleId = `m_${Math.random().toString(36).slice(2, 9)}`;
  const modal = h("div", { class: `modal${wide ? " wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
    h("header", null, h("h2", { id: titleId }, title), h("button", { class: "x", type: "button", "aria-label": "Close", onClick: close }, "×")),
    h("div", { class: "body" }, content));
  backdrop.addEventListener("mousedown", (e) => { if (e.target === backdrop) close(); });
  backdrop.append(modal);
  document.body.append(backdrop);
  document.addEventListener("keydown", onKey);
  const first = modal.querySelector("input, select, textarea, button.btn");
  if (first) first.focus();
  return { close };
}

// fields: [{name, label, type, required, placeholder, help, value, options:[{value,label}], accept, rows, maxLength}]
export function formModal({ title, fields, submitLabel = "Save", danger = false, intro, onSubmit, wide = false }) {
  const inputs = {};
  const errorBox = h("div", { class: "form-error", hidden: true, role: "alert" });
  const form = h("form", { noValidate: false });
  if (intro) form.append(typeof intro === "string" ? h("p", { class: "muted tight mb0" }, intro) : intro);
  form.append(errorBox);
  for (const f of fields) {
    let input;
    if (f.type === "select") {
      input = h("select", { name: f.name, required: !!f.required, value: f.value },
        f.options.map((o) => h("option", { value: o.value }, o.label)));
    } else if (f.type === "textarea") {
      input = h("textarea", { name: f.name, rows: f.rows || 3, maxLength: f.maxLength, placeholder: f.placeholder, value: f.value || "", class: f.className });
    } else {
      input = h("input", { name: f.name, type: f.type || "text", required: !!f.required, placeholder: f.placeholder,
        accept: f.accept, maxLength: f.maxLength, minLength: f.minLength, autocomplete: f.autocomplete || "off", value: f.value });
    }
    inputs[f.name] = input;
    form.append(field(f.label, input, f.help));
  }
  const cancel = h("button", { class: "btn", type: "button" }, "Cancel");
  const submit = h("button", { class: `btn ${danger ? "danger solid" : "primary"}`, type: "submit" }, submitLabel);
  form.append(h("footer", null, cancel, submit));
  const { close } = openModal({ title, content: form, wide });
  cancel.addEventListener("click", close);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorBox.hidden = true;
    submit.disabled = true;
    const values = {};
    for (const [name, el] of Object.entries(inputs)) values[name] = el.type === "file" ? el.files[0] || null : el.value;
    try { await onSubmit(values); close(); }
    catch (err) { errorBox.textContent = errMsg(err); errorBox.hidden = false; submit.disabled = false; }
  });
  return { close };
}

export function confirmDialog({ title, message, confirmLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v, close) => { if (!settled) { settled = true; resolve(v); } close(); };
    const yes = h("button", { class: `btn ${danger ? "danger solid" : "primary"}`, type: "button" }, confirmLabel);
    const no = h("button", { class: "btn", type: "button" }, "Cancel");
    const content = h("div", null, h("p", { class: "tight" }, message), h("footer", null, no, yes));
    const { close } = openModal({ title, content });
    yes.addEventListener("click", () => done(true, close));
    no.addEventListener("click", () => done(false, close));
    // Closing with Esc / backdrop resolves false.
    const obs = new MutationObserver(() => { if (!document.body.contains(content)) { obs.disconnect(); if (!settled) { settled = true; resolve(false); } } });
    obs.observe(document.body, { childList: true, subtree: true });
  });
}

/* ---------- effects ---------- */
export const reducedMotion = () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Animated number for dashboard cards (instant when the user prefers reduced motion).
export function countUp(el, to, ms = 900) {
  to = Number(to) || 0;
  if (reducedMotion() || to === 0 || typeof requestAnimationFrame !== "function") { el.textContent = String(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const p = Math.min(1, (t - t0) / ms);
    el.textContent = String(Math.round(to * (1 - Math.pow(1 - p, 3))));
    if (p < 1) requestAnimationFrame(step); else el.textContent = String(to);
  };
  el.textContent = "0";
  requestAnimationFrame(step);
}

export function statCard({ label, value, sub, tone = "blue", iconName = "chart", href }) {
  const num = h("div", { class: "value" }, "0");
  countUp(num, value);
  const body = [h("div", { class: `stat-icon ${tone}` }, icon(iconName, 22)), h("div", { class: "stat-text" }, h("div", { class: "label" }, label), num, sub ? h("div", { class: "sub" }, sub) : null)];
  return href ? h("a", { class: `card stat tight lift ${tone}`, href }, body) : h("div", { class: `card stat tight ${tone}` }, body);
}

export const skeleton = (rows = 4) => h("div", { class: "skeleton-list", "aria-hidden": "true" },
  Array.from({ length: rows }, () => h("div", { class: "skeleton" })));

export function tabs(items, active, onSelect) {
  return h("div", { class: "tabs", role: "tablist" }, items.map(([key, label, count]) => h("button", {
    class: `tab ${key === active ? "active" : ""}`, type: "button", role: "tab", "aria-selected": key === active ? "true" : "false",
    onClick: () => onSelect(key) }, label, count !== undefined && count !== null ? h("span", { class: "tab-count" }, String(count)) : null)));
}

export const initials = (name) => (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("") || "?";
export const avatar = (name) => h("div", { class: "avatar", "aria-hidden": "true" }, initials(name));
export { icon };
