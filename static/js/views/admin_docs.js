import { api } from "../api.js";
import { h, clear, toast, errMsg, formModal, pageHeader, card, skeleton, empty, notice, badge, reviewBadge, outcomeBadge, fmtDate, fmtBytes, table, field,
  tabs, icon } from "../ui.js";

const fail = (e) => toast(errMsg(e), "error");
const changed = () => window.dispatchEvent(new Event("tv:changed"));
const review = (id, json) => api(`/admin/documents/${id}/review`, { method: "POST", json });

function rejectDialog(d, done) {
  formModal({
    title: "Reject document", submitLabel: "Reject", danger: true,
    intro: `“${d.name}” stops being reachable by anyone except its owner, and existing shares stop working immediately. The owner sees your reason.`,
    fields: [{ name: "reason", label: "Reason for the owner", type: "textarea", required: true, maxLength: 500, placeholder: "e.g. Contains personal data that must not be shared" }],
    onSubmit: async (v) => { await review(d.id, { decision: "reject", reason: v.reason.trim() }); toast("Document rejected.", "success"); changed(); done(); },
  });
}

/* ---------- document review queue ---------- */
export async function renderDocReview(root, ctx) {
  const owner = ctx.query.get("owner") || "";
  let active = ctx.query.get("status") || "pending";
  root.append(pageHeader("Document review", owner ? `Documents uploaded by ${owner}.` : "Every uploaded document waits here until you approve it.",
    owner ? h("a", { class: "btn", href: "#/admin/documents" }, "Clear owner filter") : null));
  root.append(notice("You review metadata only: who uploaded it, what it is called, its type, size and checksum. File contents are never shown to administrators.", ""));
  const tabBar = h("div"), list = h("div");
  root.append(tabBar, list);
  const data = {};

  async function load() {
    clear(list).append(skeleton(3));
    try {
      const params = { owner: owner || undefined, limit: 200 };
      const [p, a, r] = await Promise.all(["pending", "approved", "rejected"].map((s) => api("/admin/documents", { params: { ...params, review_status: s } })));
      Object.assign(data, { pending: p, approved: a, rejected: r });
      draw();
    } catch (e) { clear(list).append(empty("Could not load documents", errMsg(e))); }
  }

  function draw() {
    clear(tabBar).append(tabs([["pending", "Awaiting review", data.pending.length], ["approved", "Approved", data.approved.length], ["rejected", "Rejected", data.rejected.length]],
      active, (k) => { active = k; draw(); }));
    const docs = data[active];
    clear(list).append(docs.length === 0 ? card(null, empty(active === "pending" ? "Nothing to review" : `No ${active} documents`, active === "pending" ? "New uploads from owners will appear here." : "")) : h("div", { class: "cands" }, docs.map(item)));
  }

  function item(d) {
    const l = d.latest;
    return h("div", { class: "cand" },
      h("div", { class: "doc-review" },
        h("div", { class: "title" }, icon("file", 18), d.name, reviewBadge(d.review_status), badge(d.category)),
        h("div", { class: "facts-line" }, `${d.owner_name} <${d.owner_email}>${d.owner_status !== "active" ? ` (${d.owner_status})` : ""} · uploaded ${l ? fmtDate(l.uploaded_at) : fmtDate(d.created_at)}${l && l.uploaded_by && l.uploaded_by !== d.owner_email ? ` by ${l.uploaded_by}` : ""}`),
        l ? h("div", { class: "facts-line" }, `${l.filename} · ${l.mime_type} · ${fmtBytes(l.size_bytes)} · v${l.version_no} · `, h("span", { class: "mono", title: l.sha256 }, `sha256 ${l.sha256.slice(0, 12)}…`)) : null,
        d.description ? h("div", null, d.description) : null,
        d.review_reason ? h("div", { class: "facts-line" }, `Reason: ${d.review_reason}`) : null),
      h("div", { class: "controls" },
        d.review_status !== "approved" ? h("button", { class: "btn success sm", type: "button", onClick: async () => { try { await review(d.id, { decision: "approve" }); toast("Approved.", "success"); changed(); load(); } catch (e) { fail(e); } } }, icon("check", 14), "Approve") : null,
        d.review_status !== "rejected" ? h("button", { class: "btn danger sm", type: "button", onClick: () => rejectDialog(d, load) }, icon("x", 14), "Reject") : null,
        h("a", { class: "btn sm", href: `#/admin/documents/${d.id}` }, "Activity")));
  }
  await load();
}

/* ---------- upload policy ---------- */
export async function renderPolicy(root) {
  const pol = await api("/admin/policy");
  root.append(pageHeader("Upload policy", "Decide what owners are allowed to upload. Changes apply to the next upload and are recorded in the audit log."));
  const boxes = pol.all_types.map((t) => {
    const cb = h("input", { type: "checkbox", value: t, checked: pol.allowed_types.includes(t) });
    return { t, cb, node: h("label", { class: "check" }, cb, `.${t}`) };
  });
  const max = h("input", { type: "number", min: 1, max: pol.server_max_mb, value: String(pol.max_mb), required: true });
  const cats = h("textarea", { rows: 4, placeholder: "One per line, e.g.\nHR\nLegal\nFinance", value: pol.categories.join("\n") });
  const error = h("div", { class: "form-error", hidden: true, role: "alert" });
  const submit = h("button", { class: "btn primary", type: "submit" }, icon("check", 16), "Save policy");
  const form = h("form", null, error,
    h("div", { class: "field" }, h("label", null, "Allowed file types"), h("div", { class: "checks" }, boxes.map((b) => b.node)), h("span", { class: "help" }, "Files are also checked on the server against their real content, not just their name.")),
    h("div", { class: "grid cols-2" }, field("Maximum file size (MB)", max, `Cannot exceed the server limit of ${pol.server_max_mb} MB.`),
      field("Allowed categories", cats, "Leave empty to let owners choose any category. When set, owners must pick one of these.")), submit);
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); error.hidden = true; submit.disabled = true;
    try {
      await api("/admin/policy", { method: "PUT", json: { allowed_types: boxes.filter((b) => b.cb.checked).map((b) => b.t), max_mb: Number(max.value),
        categories: cats.value.split(/\n|,/).map((c) => c.trim()).filter(Boolean) } });
      toast("Policy saved.", "success");
    } catch (err) { error.textContent = errMsg(err); error.hidden = false; }
    submit.disabled = false;
  });
  root.append(card(null, form));
  root.append(card("Review workflow", h("p", { class: "tight" }, pol.require_approval
    ? "Every upload and every new version waits for an administrator to approve it. Until then only its owner can open it, and it cannot be shared."
    : "Document approval is switched off on this server (REQUIRE_DOCUMENT_APPROVAL=false): uploads are available to share immediately.")));
}

/* ---------- one document's activity ---------- */
export async function renderTimeline(root, ctx) {
  const t = await api(`/admin/documents/${ctx.params[0]}/timeline`);
  root.append(h("p", { class: "small" }, h("a", { href: "#/admin/documents" }, "← Documents")));
  root.append(pageHeader(t.document ? t.document.name : "Unknown document", t.document ? `Owner: ${t.document.owner_email}` : "Only audit history remains for this id.",
    t.document && t.document.deleted ? badge("deleted", "red") : null, t.document ? reviewBadge(t.document.review_status) : null,
    t.document && !t.document.deleted && t.document.review_status !== "approved" ? h("button", { class: "btn success", type: "button", onClick: async () => { try { await review(t.document.id, { decision: "approve" }); toast("Approved.", "success"); changed(); ctx.go(`/admin/documents/${t.document.id}?r=${Date.now()}`); } catch (e) { fail(e); } } }, icon("check", 16), "Approve") : null,
    t.document && !t.document.deleted && t.document.review_status !== "rejected" ? h("button", { class: "btn danger", type: "button", onClick: () => rejectDialog(t.document, () => ctx.go(`/admin/documents/${t.document.id}?r=${Date.now()}`)) }, icon("x", 16), "Reject") : null));
  root.append(notice("This screen answers “who opened this, and when?” It includes refused attempts and never shows file contents.", ""));
  root.append(card("Who has read it", t.readers.length === 0 ? empty("Nobody has opened this document") : table(["Person", "Reads", "First", "Last"],
    t.readers.map((r) => [r.email, r.reads, fmtDate(r.first), fmtDate(r.last)]))));
  root.append(card("Who can read it now", t.current_grants.length === 0 ? empty("No active grants") : table(["Person", "Access", "Expires"],
    t.current_grants.map((g) => [g.email, g.permission, g.expires_at ? fmtDate(g.expires_at) : "Never"]))));
  root.append(card("Full history", table(["#", "When", "Person", "Action", "Outcome", "Details"], t.events.map((e) => {
    let d = "—";
    try { const o = JSON.parse(e.detail); if (o && Object.keys(o).length) d = h("details", null, h("summary", null, "view"), h("pre", null, JSON.stringify(o, null, 2))); } catch { /* ignore */ }
    return [e.id, h("span", { class: "nowrap" }, fmtDate(e.ts)), e.actor_email || "anonymous", e.action, outcomeBadge(e.outcome), d];
  }))));
}
