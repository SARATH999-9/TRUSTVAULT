import { api } from "../api.js";
import { h, clear, toast, errMsg, pageHeader, card, empty, notice, statCard, table, badge, reviewBadge, fmtDate, fmtBytes, field, icon, skeleton } from "../ui.js";
import { policyNote, uploadFields } from "./documents.js";

export async function renderOwnerDashboard(root, ctx) {
  const total = (review) => api("/documents", { params: { review, limit: 1 } }).then((d) => d.total);
  const [all, pending, approved, rejected, recent, rejectedList] = await Promise.all([
    total(""), total("pending"), total("approved"), total("rejected"),
    api("/documents", { params: { limit: 6 } }), api("/documents", { params: { review: "rejected", limit: 5 } })]);
  const first = ctx.me.name.split(" ")[0];
  root.append(h("section", { class: "card hero-card" }, h("h2", null, `Welcome back, ${first}`),
    h("p", null, "Upload or write documents, then share them with approved viewers. An administrator reviews every upload before it can be shared, and you can take access back at any time."),
    h("div", { class: "actions" }, h("a", { class: "btn primary", href: "#/documents" }, icon("upload", 16), "Upload a document"),
      h("a", { class: "btn", href: "#/owner/write" }, icon("pen", 16), "Write a document"))));
  root.append(h("div", { class: "grid cols-4" },
    statCard({ label: "My documents", value: all, tone: "blue", iconName: "file", href: "#/documents" }),
    statCard({ label: "Awaiting review", value: pending, tone: "amber", iconName: "clock", sub: "only you can see these", href: "#/documents" }),
    statCard({ label: "Approved", value: approved, tone: "green", iconName: "check", sub: "ready to share", href: "#/documents" }),
    statCard({ label: "Rejected", value: rejected, tone: "red", iconName: "alert", sub: "need your attention", href: "#/documents" })));
  if (rejectedList.items.length) {
    root.append(h("div", { class: "mt" }), card("Needs your attention", h("div", { class: "cands" }, rejectedList.items.map((d) => h("div", { class: "cand" },
      h("div", { class: "who" }, h("strong", null, d.name), " ", reviewBadge("rejected"), h("div", { class: "muted small" }, d.review_reason || "No reason given")),
      h("a", { class: "btn sm", href: `#/documents/${d.id}` }, "Open and fix"))))));
  }
  root.append(card("Recent documents", recent.items.length === 0
    ? empty("No documents yet", "Upload a file or write a document to get started.")
    : table(["Name", "Category", "Status", "Latest", "Created"], recent.items.map((d) => [
      h("a", { href: `#/documents/${d.id}` }, d.name), badge(d.category), reviewBadge(d.review_status),
      d.latest_version ? `v${d.latest_version.version_no} · ${fmtBytes(d.latest_version.size_bytes)}` : "—", fmtDate(d.created_at)]))));
}

// Write a text document in the browser; it then goes through the same review and sharing rules as an upload.
export async function renderWrite(root, ctx) {
  const pol = await api("/policy");
  root.append(pageHeader("Write a document", "Compose a text document here instead of uploading a file."));
  if (!pol.allowed_types.includes("txt")) {
    root.append(card(null, empty("Writing is switched off", "Your administrator has not allowed text documents. You can still upload files.")));
    return;
  }
  const title = h("input", { type: "text", required: true, maxLength: 200, placeholder: "Meeting notes, policy draft…" });
  const body = h("textarea", { class: "editor", required: true, maxLength: 200000, placeholder: "Start writing…" });
  const count = h("span", { class: "muted small" }, "0 / 200,000 characters");
  body.addEventListener("input", () => { count.textContent = `${body.value.length.toLocaleString()} / 200,000 characters`; });
  const extra = {};
  const meta = uploadFields(pol, { withFile: false }).map((f) => {
    const input = f.type === "select" ? h("select", null, f.options.map((o) => h("option", { value: o.value }, o.label)))
      : f.type === "textarea" ? h("textarea", { maxLength: f.maxLength, rows: 2 }) : h("input", { type: "text", value: f.value, maxLength: f.maxLength });
    extra[f.name] = input;
    return field(f.label, input, f.help);
  });
  const error = h("div", { class: "form-error", hidden: true, role: "alert" });
  const submit = h("button", { class: "btn primary", type: "submit" }, icon("check", 16), "Save as document");
  const form = h("form", null, error, h("div", { class: "grid cols-2" }, field("Title", title), meta[0]), meta[1],
    field("Content", body), h("div", { class: "actions" }, submit, count));
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); error.hidden = true; submit.disabled = true;
    try {
      const doc = await api("/documents/compose", { method: "POST", json: { name: title.value, category: extra.category.value || "general", description: extra.description.value, content: body.value } });
      toast(pol.require_approval ? "Saved. It is waiting for administrator review." : "Document saved.", "success");
      ctx.go(`/documents/${doc.id}`);
    } catch (err) { error.textContent = errMsg(err); error.hidden = false; submit.disabled = false; }
  });
  root.append(card(null, notice(policyNote(pol), ""), form));
}
