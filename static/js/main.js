import { api } from "./api.js";
import { h, clear, toast, loading, empty, roleBadge, avatar, icon, errMsg } from "./ui.js";
import { showSplash } from "./views/splash.js";
import { renderAuth } from "./views/auth.js";
import { renderPending, stopPolling } from "./views/pending.js";
import { renderDocuments } from "./views/documents.js";
import { renderDocument } from "./views/document.js";
import { renderOwnerDashboard, renderWrite } from "./views/owner.js";
import { renderAccount } from "./views/account.js";
import { renderDashboard, renderAudit, renderAlerts } from "./views/admin.js";
import { renderApprovals, renderUsers, renderOwners } from "./views/admin_people.js";
import { renderDocReview, renderPolicy, renderTimeline } from "./views/admin_docs.js";

const app = document.getElementById("app");
const ID = "([0-9a-fA-F-]{36})";
const ANY = ["owner", "viewer", "admin"], DOCS = ["owner", "viewer"], ADMIN = ["admin"], OWNER = ["owner"];
// Navigation is a convenience only: the server enforces every one of these screens again.
const routes = [
  { re: /^\/documents$/, roles: DOCS, view: renderDocuments, title: "Documents" },
  { re: new RegExp(`^/documents/${ID}$`), roles: DOCS, view: renderDocument, title: "Document" },
  { re: /^\/owner$/, roles: OWNER, view: renderOwnerDashboard, title: "Owner dashboard" },
  { re: /^\/owner\/write$/, roles: OWNER, view: renderWrite, title: "Write a document" },
  { re: /^\/account$/, roles: ANY, view: renderAccount, title: "Account" },
  { re: /^\/admin$/, roles: ADMIN, view: renderDashboard, title: "Overview" },
  { re: /^\/admin\/approvals$/, roles: ADMIN, view: renderApprovals, title: "Approvals" },
  { re: /^\/admin\/users$/, roles: ADMIN, view: renderUsers, title: "Users" },
  { re: /^\/admin\/owners$/, roles: ADMIN, view: renderOwners, title: "Owners" },
  { re: /^\/admin\/documents$/, roles: ADMIN, view: renderDocReview, title: "Document review" },
  { re: new RegExp(`^/admin/documents/${ID}$`), roles: ADMIN, view: renderTimeline, title: "Document activity" },
  { re: /^\/admin\/policy$/, roles: ADMIN, view: renderPolicy, title: "Upload policy" },
  { re: /^\/admin\/alerts$/, roles: ADMIN, view: renderAlerts, title: "Alerts" },
  { re: /^\/admin\/audit$/, roles: ADMIN, view: renderAudit, title: "Audit log" },
];

let me = null;
let config = { google_client_id: null };
let navToken = 0;
let splashShown = false;

const home = () => (me.role === "admin" ? "/admin" : me.role === "owner" ? "/owner" : "/documents");
export const go = (path) => { location.hash = `#${path}`; };

function parseHash() {
  const raw = location.hash.slice(1) || "/";
  const [path, qs = ""] = raw.split("?");
  return { path, query: new URLSearchParams(qs) };
}

function navItems() {
  if (me.role === "admin") {
    return [["group", "Administration"], ["/admin", "Overview", "grid"], ["/admin/approvals", "Approvals", "users", "users"], ["/admin/documents", "Document review", "file", "documents"],
      ["/admin/users", "Users", "user"], ["/admin/owners", "Owners", "building"], ["/admin/policy", "Upload policy", "sliders"],
      ["group", "Oversight"], ["/admin/alerts", "Alerts", "alert"], ["/admin/audit", "Audit log", "history"], ["group", "Account"], ["/account", "My account", "lock"]];
  }
  if (me.role === "owner") return [["/owner", "Dashboard", "grid"], ["/documents", "My documents", "file"], ["/owner/write", "Write a document", "pen"], ["/account", "My account", "lock"]];
  return [["/documents", "Shared with me", "file"], ["/account", "My account", "lock"]];
}

function shell(activePath) {
  const links = navItems().map(([path, label, ic, badgeKey]) => {
    if (path === "group") return h("div", { class: "group" }, label);
    const on = activePath === path || (path !== "/admin" && path !== "/documents" && activePath.startsWith(`${path}/`)) || (path === "/documents" && activePath.startsWith("/documents"));
    return h("a", { href: `#${path}`, class: on ? "active" : "" }, icon(ic, 18), label,
      badgeKey ? h("span", { class: "count", "data-badge": badgeKey, hidden: true }) : null);
  });
  const main = h("main", { class: "main", id: "view", tabIndex: -1 });
  clear(app).append(h("div", { class: "shell" },
    h("aside", { class: "sidebar" },
      h("div", { class: "brand" }, h("img", { class: "logo", src: "/static/favicon.svg", alt: "" }), "TrustVault"),
      h("nav", { class: "nav", "aria-label": "Main" }, links),
      h("div", { class: "userbox" }, h("div", { class: "who" }, avatar(me.name), h("div", null, h("div", { class: "name" }, me.name), h("div", { class: "email" }, me.email), roleBadge(me.role))),
        h("button", { class: "btn sm", type: "button", onClick: doLogout }, icon("logout", 16), "Sign out"))),
    main));
  return main;
}

async function refreshBadges() {
  if (!me || me.role !== "admin" || me.status !== "active") return;
  try {
    const c = await api("/admin/pending-counts");
    for (const el of document.querySelectorAll("[data-badge]")) {
      const n = c[el.getAttribute("data-badge")] || 0;
      el.textContent = String(n); el.hidden = n === 0;
    }
  } catch { /* badges are a nicety */ }
}

async function doLogout() {
  stopPolling();
  try { await api("/auth/logout", { method: "POST" }); } catch { /* session may already be gone */ }
  me = null;
  go("/login");
  render();
}

const onLogin = (user) => { me = user; if (location.hash === "#/" || location.hash === "") render(); else go("/"); };

async function render() {
  const token = ++navToken;
  stopPolling();
  const { path, query } = parseHash();
  if (!me) {
    document.title = "Sign in · TrustVault";
    if (location.hash !== "#/login") { history.replaceState(null, "", "#/login"); }
    return renderAuth(app, { config, onLogin });
  }
  if (me.status === "pending") {
    document.title = "Waiting for approval · TrustVault";
    return renderPending(app, { me, onChange: (u) => { me = u; go("/"); render(); }, onLogout: doLogout });
  }
  if (path === "/" || path === "/login") { go(home()); return; }
  const route = routes.find((r) => r.re.test(path));
  if (!route) { const main = shell(path); main.append(empty("Page not found", "That page does not exist.")); return; }
  if (!route.roles.includes(me.role)) { toast("You do not have access to that page.", "error"); go(home()); return; }
  const params = route.re.exec(path).slice(1);
  const main = shell(path);
  refreshBadges();
  document.title = `${route.title} · TrustVault`;
  main.append(loading());
  const stage = h("div", { class: "view-enter" });
  try {
    await route.view(stage, { me, params, query, go, config });
    if (token !== navToken) return;                  // user navigated away while loading
    clear(main).append(stage);
    main.focus({ preventScroll: true });
  } catch (e) {
    if (token !== navToken) return;
    clear(main).append(empty("Could not load this page", errMsg(e)));
  }
}

window.addEventListener("hashchange", render);
window.addEventListener("tv:changed", refreshBadges);
window.addEventListener("tv:unauth", () => {
  if (!me) return;
  me = null;
  toast("Your session has ended. Please sign in again.", "error");
  render();
});

(async function boot() {
  const [cfg, who] = await Promise.allSettled([api("/auth/config"), api("/auth/me")]);
  if (cfg.status === "fulfilled") config = cfg.value;
  me = who.status === "fulfilled" ? who.value : null;
  if (!me && !splashShown) { splashShown = true; await showSplash(app); }
  if (!location.hash || location.hash === "#" || location.hash === "#/") history.replaceState(null, "", me ? `#${home()}` : "#/login");
  render();
})();
