import { api, downloadFile } from "../api.js";
import { h, clear, toast, errMsg, formModal, pageHeader, skeleton, empty, accessBadge, reviewBadge, badge, fmtDate, fmtBytes,
  dayStart, dayEnd, field, table, icon, notice } from "../ui.js";

const LIMIT = 15;

export function uploadFields(pol, { withFile = true } = {}) {
  const fields = [];
  if (withFile) fields.push({ name: "file", label: "File", type: "file", required: true, accept: pol.allowed_types.map((t) => `.${t}`).join(",") });
  if (withFile) fields.push({ name: "name", label: "Display name", placeholder: "Defaults to the file name", maxLength: 255 });
  fields.push(pol.categories.length
    ? { name: "category", label: "Category", type: "select", options: pol.categories.map((c) => ({ value: c, label: c })), help: "Your administrator limits which categories can be used." }
    : { name: "category", label: "Category", value: "general", maxLength: 60, help: "Letters, numbers, spaces, . & -" });
  fields.push({ name: "description", label: "Description", type: "textarea", maxLength: 2000 });
  return fields;
}

export const policyNote = (pol) => `Allowed: ${pol.allowed_types.join(", ").toUpperCase()} · up to ${pol.max_mb} MB.` +
  (pol.require_approval ? " An administrator reviews every upload before it can be shared." : "");

export async function renderDocuments(root, ctx) {
  const isOwner = ctx.me.role === "owner";
  const state = { offset: 0 };
  const inputs = {
    q: h("input", { type: "search", maxLength: 100, placeholder: "Name contains…" }),
    owner: h("input", { type: "search", maxLength: 100, placeholder: "Name or email" }),
    category: h("input", { type: "search", maxLength: 60, placeholder: "e.g. hr" }),
    from: h("input", { type: "date" }), to: h("input", { type: "date" }),
    review: h("select", null, h("option", { value: "" }, "Any status"), h("option", { value: "pending" }, "Awaiting review"),
      h("option", { value: "approved" }, "Approved"), h("option", { value: "rejected" }, "Rejected")),
  };
  const results = h("div");

  root.append(pageHeader(isOwner ? "My documents" : "Shared with me",
    isOwner ? "Everything you own, with its review status. Documents shared with you also appear here." : "Documents the owners have shared with you.",
    isOwner ? h("a", { class: "btn", href: "#/owner/write" }, icon("pen", 16), "Write document") : null,
    isOwner ? h("button", { class: "btn primary", type: "button", onClick: openUpload }, icon("upload", 16), "Upload document") : null));

  const form = h("form", { class: "filters", role: "search" },
    field("Name", inputs.q), field("Owner", inputs.owner), field("Category", inputs.category),
    isOwner ? field("Status", inputs.review) : null, field("Created from", inputs.from), field("Created to", inputs.to),
    h("div", { class: "actions" }, h("button", { class: "btn primary", type: "submit" }, "Search"),
      h("button", { class: "btn", type: "button", onClick: () => { form.reset(); state.offset = 0; load(); } }, "Clear")));
  form.addEventListener("submit", (e) => { e.preventDefault(); state.offset = 0; load(); });
  root.append(h("section", { class: "card" }, form), results);

  const filtersActive = () => Object.values(inputs).some((i) => i.value.trim() !== "");

  async function load() {
    clear(results).append(skeleton(4));
    try {
      const data = await api("/documents", { params: {
        q: inputs.q.value.trim(), owner: inputs.owner.value.trim(), category: inputs.category.value.trim(), review: inputs.review.value,
        created_from: dayStart(inputs.from.value), created_to: dayEnd(inputs.to.value), limit: LIMIT, offset: state.offset } });
      clear(results).append(renderTable(data));
    } catch (e) { clear(results).append(empty("Could not load documents", errMsg(e))); }
  }

  function renderTable(data) {
    if (data.total === 0) {
      return h("section", { class: "card" }, filtersActive()
        ? empty("No matching documents", "Try different search terms. Only documents you have access to are searched.")
        : isOwner ? empty("No documents yet", "Upload a file or write a document to get started.")
          : empty("Nothing shared with you yet", "Documents appear here once an owner shares them with you and an administrator has approved them."));
    }
    const head = ["Name", "Category", "Owner", ...(isOwner ? ["Status"] : []), "Your access", "Latest", "Created", ""];
    const rows = data.items.map((d) => [
      h("a", { href: `#/documents/${d.id}` }, d.name), badge(d.category),
      h("span", null, d.owner.name, h("div", { class: "muted small" }, d.owner.email)),
      ...(isOwner ? [reviewBadge(d.review_status)] : []), accessBadge(d.my_access),
      d.latest_version ? h("span", { class: "nowrap" }, `v${d.latest_version.version_no} · ${fmtBytes(d.latest_version.size_bytes)}`) : "—",
      h("span", { class: "nowrap" }, fmtDate(d.created_at)),
      h("div", { class: "row-actions" }, h("a", { class: "btn sm", href: `#/documents/${d.id}` }, "Open"),
        h("button", { class: "btn sm", type: "button", onClick: () => downloadFile(`/documents/${d.id}/download`, d.name).catch((e) => toast(errMsg(e), "error")) }, "Download")),
    ]);
    const from = state.offset + 1, to = Math.min(state.offset + LIMIT, data.total);
    return h("section", { class: "card" }, table(head, rows),
      h("div", { class: "pager" }, `${from}–${to} of ${data.total}`,
        h("button", { class: "btn sm", type: "button", disabled: state.offset === 0, onClick: () => { state.offset = Math.max(0, state.offset - LIMIT); load(); } }, "Previous"),
        h("button", { class: "btn sm", type: "button", disabled: to >= data.total, onClick: () => { state.offset += LIMIT; load(); } }, "Next")));
  }

  async function openUpload() {
    let pol;
    try { pol = await api("/policy"); } catch (e) { toast(errMsg(e), "error"); return; }
    formModal({
      title: "Upload document", submitLabel: "Upload", intro: policyNote(pol), fields: uploadFields(pol),
      onSubmit: async (v) => {
        const fd = new FormData();
        fd.append("file", v.file);
        if (v.name.trim()) fd.append("name", v.name.trim());
        fd.append("category", v.category.trim() || "general");
        fd.append("description", v.description);
        const doc = await api("/documents", { method: "POST", form: fd });
        toast(pol.require_approval ? "Uploaded. It is waiting for administrator review." : "Document uploaded.", "success");
        ctx.go(`/documents/${doc.id}`);
      },
    });
  }
  await load();
}
