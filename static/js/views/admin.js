import { api } from "../api.js";
import { h, clear, toast, errMsg, pageHeader, card, loading, skeleton, empty, notice, outcomeBadge, severityBadge, fmtDate, shortId, table, field,
  dayStart, dayEnd, statCard, badge, icon } from "../ui.js";

const sevOrder = ["critical", "high", "medium", "info"];

/* ---------- shared: audit chain verification ---------- */
export function verifyPanel() {
  const out = h("div", { class: "mt" });
  const btn = h("button", { class: "btn", type: "button" }, icon("shield", 16), "Verify audit chain");
  btn.addEventListener("click", async () => {
    btn.disabled = true; clear(out).append(loading("Verifying every row…"));
    try {
      const r = await api("/admin/audit/verify");
      clear(out).append(r.ok
        ? notice(h("span", null, `Chain intact: ${r.rows_checked} rows verified. Head hash: `, h("code", null, r.head_hash || "(empty log)"),
          h("div", { class: "small muted" }, "Copy this hash somewhere outside the system. If the newest rows were ever deleted, only a saved head hash can show it.")), "ok")
        : notice(`TAMPERING DETECTED. The chain breaks at row ${r.first_bad_id} after ${r.rows_checked} good rows.`, "bad"));
    } catch (e) { clear(out).append(empty("Verification failed", errMsg(e))); }
    btn.disabled = false;
  });
  return h("div", null, btn, out);
}

export function alertList(alerts) {
  return h("div", { class: "cands" }, alerts.map((a) => h("div", { class: "cand" },
    h("div", { class: "who" }, severityBadge(a.severity), " ", h("strong", null, a.rule.replaceAll("_", " ")),
      h("div", null, a.message),
      h("div", { class: "muted small" }, `${a.count} event(s) · ${fmtDate(a.first_seen)} → ${fmtDate(a.last_seen)}`)),
    h("div", { class: "controls" },
      a.actor_email ? h("a", { class: "btn sm", href: `#/admin/audit?actor=${encodeURIComponent(a.actor_email)}` }, "Their activity") : null,
      a.document_id ? h("a", { class: "btn sm", href: `#/admin/documents/${a.document_id}` }, "Document timeline") : null))));
}

/* ---------- overview ---------- */
export async function renderDashboard(root) {
  const [sum, al] = await Promise.all([api("/admin/summary"), api("/admin/alerts")]);
  const r = sum.users_by_role;
  root.append(pageHeader("Overview", `Activity in the last ${sum.window_hours} hours.`));

  const waiting = sum.pending_users + sum.pending_documents;
  root.append(waiting === 0
    ? h("section", { class: "card hero-card" }, h("h2", null, "Nothing is waiting for you"), h("p", null, "No accounts or documents are waiting for approval. New requests will appear here."))
    : h("section", { class: "card hero-card" }, h("h2", null, "Action needed"), h("p", null, "People and documents wait until an administrator approves them. Nobody else can see them in the meantime."),
      h("div", { class: "actions" },
        sum.pending_users ? h("a", { class: "btn primary", href: "#/admin/approvals" }, icon("users", 16), `${sum.pending_users} account${sum.pending_users === 1 ? "" : "s"} to approve`) : null,
        sum.pending_documents ? h("a", { class: "btn", href: "#/admin/documents" }, icon("file", 16), `${sum.pending_documents} document${sum.pending_documents === 1 ? "" : "s"} to review`) : null)));

  root.append(h("div", { class: "grid cols-4" },
    statCard({ label: "Users", value: (r.admin || 0) + (r.owner || 0) + (r.viewer || 0), sub: `${r.admin || 0} admin · ${r.owner || 0} owner · ${r.viewer || 0} viewer`, tone: "blue", iconName: "users", href: "#/admin/users" }),
    statCard({ label: "Waiting approval", value: sum.pending_users, sub: "accounts", tone: "amber", iconName: "clock", href: "#/admin/approvals" }),
    statCard({ label: "Documents", value: sum.documents, sub: `${sum.pending_documents} awaiting review · ${sum.documents_deleted} deleted`, tone: "teal", iconName: "file", href: "#/admin/documents" }),
    statCard({ label: "Events", value: (sum.events.allowed || 0) + (sum.events.denied || 0), sub: `${sum.events.denied || 0} refused · ${sum.grants} active grants`, tone: "violet", iconName: "history", href: "#/admin/audit" })));

  const top = al.alerts.slice(0, 5);
  root.append(h("div", { class: "mt" }), card("Worth noticing",
    top.length === 0 ? empty("All quiet", "No alerts in this window.") : alertList(top),
    h("p", { class: "mb0 mt" }, h("a", { href: "#/admin/alerts" }, "All alerts →"))));
  root.append(card("Evidence integrity", h("p", { class: "muted tight" }, "The audit log is append-only and hash-chained. Verify that no row has been altered or removed."), verifyPanel()));
}

/* ---------- alerts ---------- */
export async function renderAlerts(root, ctx) {
  const hours = Number(ctx.query.get("hours")) || 24;
  const data = await api("/admin/alerts", { params: { hours } });
  const sel = h("select", { "aria-label": "Time window", value: String(hours) },
    [[1, "Last hour"], [24, "Last 24 hours"], [72, "Last 3 days"], [168, "Last 7 days"], [720, "Last 30 days"]].map(([v, l]) => h("option", { value: String(v) }, l)));
  sel.addEventListener("change", () => ctx.go(`/admin/alerts?hours=${sel.value}`));
  root.append(pageHeader("Alerts", "Patterns worth a human look. Alerts only inform: they never block anyone or change access.", sel));
  const sorted = [...data.alerts].sort((a, b) => sevOrder.indexOf(a.severity) - sevOrder.indexOf(b.severity));
  root.append(data.alerts.length === 0 ? card(null, empty("All quiet", "Nothing unusual in this window.")) : card(null, alertList(sorted)));
}

/* ---------- audit log ---------- */
export async function renderAudit(root, ctx) {
  const LIMIT = 50;
  const q = ctx.query;
  const state = { offset: 0 };
  const inputs = {
    actor: h("input", { type: "search", value: q.get("actor") || "", placeholder: "Email contains…", maxLength: 100 }),
    action: h("input", { type: "search", value: q.get("action") || "", placeholder: "e.g. download", maxLength: 40 }),
    outcome: h("select", { value: q.get("outcome") || "" }, h("option", { value: "" }, "Any"), h("option", { value: "allowed" }, "Allowed"), h("option", { value: "denied" }, "Refused")),
    document_id: h("input", { type: "search", value: q.get("document_id") || "", placeholder: "Document id", maxLength: 36 }),
    since: h("input", { type: "date" }), until: h("input", { type: "date" }),
  };
  const out = h("div");
  const form = h("form", { class: "filters" },
    field("Person", inputs.actor), field("Action", inputs.action), field("Outcome", inputs.outcome),
    field("Document id", inputs.document_id), field("From", inputs.since), field("To", inputs.until),
    h("div", { class: "actions" }, h("button", { class: "btn primary", type: "submit" }, "Filter"),
      h("button", { class: "btn", type: "button", onClick: () => { for (const i of Object.values(inputs)) i.value = ""; state.offset = 0; load(); } }, "Clear")));
  form.addEventListener("submit", (e) => { e.preventDefault(); state.offset = 0; load(); });
  root.append(pageHeader("Audit log", "Every sign-up, approval, upload, download, change, deletion and permission change, including refused attempts. Newest first."),
    h("section", { class: "card" }, form), out, card("Integrity", verifyPanel()));

  const detailCell = (raw) => {
    let pretty = raw;
    try { const o = JSON.parse(raw); if (!o || Object.keys(o).length === 0) return h("span", { class: "muted" }, "—"); pretty = JSON.stringify(o, null, 2); } catch { /* show raw */ }
    return h("details", null, h("summary", null, "view"), h("pre", null, pretty));
  };

  async function load() {
    clear(out).append(skeleton(5));
    try {
      const rows = await api("/admin/audit", { params: {
        actor: inputs.actor.value.trim(), action: inputs.action.value.trim(), outcome: inputs.outcome.value,
        document_id: inputs.document_id.value.trim(), since: dayStart(inputs.since.value), until: dayEnd(inputs.until.value),
        limit: LIMIT, offset: state.offset } });
      clear(out).append(card(null, rows.length === 0 ? empty("No matching events") : table(
        ["#", "When", "Person", "Action", "Outcome", "Document", "IP", "Details"],
        rows.map((r) => [r.id, h("span", { class: "nowrap" }, fmtDate(r.ts)), r.actor_email || h("span", { class: "muted" }, "anonymous"), r.action, outcomeBadge(r.outcome),
          r.document_id ? h("a", { href: `#/admin/documents/${r.document_id}`, title: r.document_id }, shortId(r.document_id)) : "—",
          r.ip || "—", detailCell(r.detail)])),
        h("div", { class: "pager" }, `Showing ${state.offset + 1}–${state.offset + rows.length}`,
          h("button", { class: "btn sm", type: "button", disabled: state.offset === 0, onClick: () => { state.offset = Math.max(0, state.offset - LIMIT); load(); } }, "Newer"),
          h("button", { class: "btn sm", type: "button", disabled: rows.length < LIMIT, onClick: () => { state.offset += LIMIT; load(); } }, "Older"))));
    } catch (e) { clear(out).append(empty("Could not load the audit log", errMsg(e))); }
  }
  await load();
}
