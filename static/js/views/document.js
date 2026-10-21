import { api, downloadFile, fetchFile } from "../api.js";
import { h, clear, toast, errMsg, formModal, confirmDialog, openModal, pageHeader, card, loading, empty, notice, badge, accessBadge,
  reviewBadge, roleBadge, fmtDate, fmtBytes, table, field, icon } from "../ui.js";
import { uploadFields } from "./documents.js";

const fail = (e) => toast(errMsg(e), "error");
const extOf = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");
const TEXT = ["txt"], IMAGES = ["png", "jpg", "jpeg"];

export async function renderDocument(root, ctx) {
  const id = ctx.params[0];
  const doc = await api(`/documents/${id}`);
  const canEdit = doc.my_access === "owner" || doc.my_access === "edit";
  const isOwner = doc.my_access === "owner";
  const latest = doc.versions[doc.versions.length - 1];
  const ext = latest ? extOf(latest.original_filename) : "";
  const isText = TEXT.includes(ext);
  const previewable = isText || IMAGES.includes(ext);
  const approved = doc.review_status === "approved";
  const path = (versionId) => `/documents/${id}/download${versionId ? `?version=${versionId}` : ""}`;
  const dl = (versionId, name) => downloadFile(path(versionId), name).catch(fail);

  root.append(h("p", { class: "small" }, h("a", { href: "#/documents" }, "← All documents")));
  root.append(pageHeader(doc.name, null,
    previewable ? h("button", { class: "btn", type: "button", onClick: () => preview(null) }, icon("eye", 16), "Preview") : null,
    h("button", { class: "btn primary", type: "button", onClick: () => dl(null, latest && latest.original_filename) }, icon("download", 16), "Download"),
    canEdit && isText ? h("button", { class: "btn", type: "button", onClick: openTextEditor }, icon("pen", 16), "Edit text") : null,
    canEdit ? h("button", { class: "btn", type: "button", onClick: openEdit }, "Edit details") : null,
    canEdit ? h("button", { class: "btn", type: "button", onClick: openNewVersion }, icon("upload", 16), "New version") : null,
    isOwner ? h("button", { class: "btn danger", type: "button", onClick: doDelete }, icon("trash", 16), "Delete") : null));

  if (isOwner) {
    if (doc.review_status === "pending") root.append(notice("Waiting for administrator review. Only you can open this document until it is approved, and it cannot be shared yet.", "warn"));
    else if (doc.review_status === "rejected") root.append(notice(`Rejected by an administrator${doc.review_reason ? `: ${doc.review_reason}` : "."} Upload a corrected new version to ask for another review.`, "bad"));
    else root.append(notice("Approved by an administrator. You can share it with people below.", "ok"));
  }

  root.append(card("Details", h("dl", { class: "kv" },
    h("dt", null, "Owner"), h("dd", null, `${doc.owner.name} (${doc.owner.email})`),
    h("dt", null, "Category"), h("dd", null, badge(doc.category)),
    h("dt", null, "Status"), h("dd", null, reviewBadge(doc.review_status)),
    h("dt", null, "Your access"), h("dd", null, accessBadge(doc.my_access)),
    h("dt", null, "Created"), h("dd", null, fmtDate(doc.created_at)),
    h("dt", null, "Description"), h("dd", null, doc.description || h("span", { class: "muted" }, "No description")))));

  root.append(card("Versions", table(["Version", "File", "Size", "Uploaded by", "Uploaded", "SHA-256", ""],
    [...doc.versions].reverse().map((v) => [
      `v${v.version_no}`, v.original_filename, fmtBytes(v.size_bytes), v.uploaded_by || "—", h("span", { class: "nowrap" }, fmtDate(v.created_at)),
      h("span", { class: "mono", title: v.sha256 }, `${v.sha256.slice(0, 12)}…`),
      h("div", { class: "row-actions" },
        IMAGES.concat(TEXT).includes(extOf(v.original_filename)) ? h("button", { class: "btn sm", type: "button", onClick: () => preview(v.id) }, "Preview") : null,
        h("button", { class: "btn sm", type: "button", onClick: () => dl(v.id, v.original_filename) }, "Download"))]))));

  if (isOwner) {
    const sharing = h("div"), ai = h("div");
    root.append(card("Who has access", sharing));
    if (approved) {
      root.append(card("Suggested people", ai));
      await renderSharing(sharing, id, () => renderSuggestions(ai, id, () => renderSharing(sharing, id, null)));
    } else {
      sharing.append(notice("Sharing is locked until an administrator approves this document.", "warn"));
    }
  } else {
    root.append(notice("Only the document owner can see or change who has access.", ""));
  }

  /* ---- preview: the same audited download, shown in the page. Text is inserted as text, never as markup ---- */
  async function preview(versionId) {
    try {
      const { blob, name } = await fetchFile(path(versionId));
      const kind = extOf(name || latest.original_filename);
      let content;
      if (TEXT.includes(kind)) content = h("pre", { class: "preview-text" }, await blob.text());
      else if (IMAGES.includes(kind)) { const url = URL.createObjectURL(blob); content = h("img", { class: "preview-img", src: url, alt: name || "preview" }); content.addEventListener("load", () => URL.revokeObjectURL(url)); }
      else content = notice("This file type cannot be previewed. Download it instead.", "");
      openModal({ title: name || "Preview", content, wide: true });
    } catch (e) { fail(e); }
  }

  async function openTextEditor() {
    let text;
    try { text = await (await fetchFile(path(null))).blob.text(); } catch (e) { fail(e); return; }
    formModal({
      title: "Edit text", submitLabel: "Save new version", wide: true,
      intro: "Saving creates a new version; the old one is kept. An administrator must approve it again before it is shared.",
      fields: [{ name: "content", label: "Content", type: "textarea", value: text, rows: 16, maxLength: 200000, className: "editor", required: true }],
      onSubmit: async (v) => {
        await api(`/documents/${id}/versions/text`, { method: "POST", json: { content: v.content } });
        toast("New version saved.", "success");
        ctx.go(`/documents/${id}?r=${Date.now()}`);
      },
    });
  }

  async function openEdit() {
    const pol = await api("/policy").catch(() => ({ categories: [], allowed_types: [], max_mb: 0 }));
    const cat = uploadFields(pol, { withFile: false })[0];
    formModal({
      title: "Edit details", submitLabel: "Save changes",
      fields: [{ name: "name", label: "Display name", value: doc.name, required: true, maxLength: 255 },
        { ...cat, value: doc.category }, { name: "description", label: "Description", type: "textarea", value: doc.description, maxLength: 2000 }],
      onSubmit: async (v) => {
        await api(`/documents/${id}`, { method: "PATCH", json: { name: v.name, category: v.category, description: v.description } });
        toast("Details saved.", "success");
        ctx.go(`/documents/${id}?r=${Date.now()}`);
      },
    });
  }

  async function openNewVersion() {
    const pol = await api("/policy").catch(() => ({ allowed_types: [] }));
    formModal({
      title: "Upload new version", submitLabel: "Upload",
      intro: "The previous version is kept. An administrator must approve the new content before it is shared again.",
      fields: [{ name: "file", label: "File", type: "file", required: true, accept: pol.allowed_types.map((t) => `.${t}`).join(",") }],
      onSubmit: async (v) => {
        const fd = new FormData(); fd.append("file", v.file);
        await api(`/documents/${id}/versions`, { method: "POST", form: fd });
        toast("New version uploaded.", "success");
        ctx.go(`/documents/${id}?r=${Date.now()}`);
      },
    });
  }

  async function doDelete() {
    const ok = await confirmDialog({ title: "Delete document?", danger: true, confirmLabel: "Delete",
      message: `“${doc.name}” will disappear for everyone, including people it is shared with. An administrator can still see that it existed.` });
    if (!ok) return;
    try { await api(`/documents/${id}`, { method: "DELETE" }); toast("Document deleted.", "success"); ctx.go("/documents"); }
    catch (e) { fail(e); }
  }
}

/* ---------------- sharing (owner only) ---------------- */
async function renderSharing(box, id, onChange) {
  clear(box).append(loading());
  let grants;
  try { grants = await api(`/documents/${id}/grants`); }
  catch (e) { clear(box).append(empty("Could not load sharing", errMsg(e))); return; }
  const reload = async () => { await renderSharing(box, id, onChange); };

  const list = grants.length === 0
    ? empty("Not shared with anyone", "Only you can open this document.")
    : table(["Person", "Role", "Access", "Expires", ""], grants.map((g) => {
      const roles = g.user.role === "viewer" ? ["read"] : ["read", "edit"];
      const sel = h("select", { "aria-label": `Access for ${g.user.email}`, value: g.permission },
        roles.map((r) => h("option", { value: r }, r === "read" ? "Can read" : "Can edit")));
      sel.addEventListener("change", async () => {
        try {
          await api(`/documents/${id}/grants`, { method: "POST", json: { email: g.user.email, permission: sel.value, expires_at: g.expires_at || undefined } });
          toast("Access updated.", "success");
        } catch (e) { fail(e); }
        reload();
      });
      return [h("span", null, g.user.name, h("div", { class: "muted small" }, g.user.email)), roleBadge(g.user.role), sel,
        g.expires_at ? fmtDate(g.expires_at) : h("span", { class: "muted" }, "Never"),
        h("button", { class: "btn sm danger", type: "button", onClick: async () => {
          const ok = await confirmDialog({ title: "Revoke access?", danger: true, confirmLabel: "Revoke",
            message: `${g.user.email} will lose access immediately. Their next request is refused.` });
          if (!ok) return;
          try { await api(`/documents/${id}/grants/${g.id}`, { method: "DELETE" }); toast("Access revoked.", "success"); } catch (e) { fail(e); }
          reload();
        } }, "Revoke")];
    }));

  const email = h("input", { type: "email", required: true, placeholder: "colleague@company.com", maxLength: 254 });
  const perm = h("select", null, h("option", { value: "read" }, "Can read"), h("option", { value: "edit" }, "Can edit"));
  const expires = h("input", { type: "datetime-local" });
  const error = h("div", { class: "form-error", hidden: true, role: "alert" });
  const add = h("form", { class: "inline-form mt" },
    field("Share with (email)", email), field("Access", perm), field("Expires (optional)", expires),
    h("button", { class: "btn primary", type: "submit" }, "Share"));
  add.addEventListener("submit", async (e) => {
    e.preventDefault(); error.hidden = true;
    try {
      await api(`/documents/${id}/grants`, { method: "POST", json: { email: email.value.trim(), permission: perm.value,
        expires_at: expires.value ? new Date(expires.value).toISOString() : undefined } });
      toast("Shared.", "success");
      await reload();
    } catch (err) { error.textContent = errMsg(err); error.hidden = false; }
  });
  clear(box).append(list, error, add,
    h("p", { class: "muted small mb0 mt" }, "People must have an approved account. Viewers can only receive read access, and administrators cannot be given access to documents."));
  if (onChange) onChange();
}

/* ---------------- AI / rule-based suggestions (propose only) ---------------- */
function renderSuggestions(box, id, refreshGrants) {
  clear(box);
  const ask = h("button", { class: "btn", type: "button" }, icon("star", 16), "Suggest who should have access");
  box.append(
    notice("Suggestions never change access. Nothing is shared until you press Share next to a person, and both the suggestion and your decision are recorded in the audit log.", ""),
    ask);
  const area = h("div", { class: "mt" });
  box.append(area);
  ask.addEventListener("click", async () => {
    ask.disabled = true; clear(area).append(loading("Looking at who you usually share with…"));
    try { show(await api(`/documents/${id}/suggestions`, { method: "POST" })); }
    catch (e) { clear(area).append(empty("No suggestion", errMsg(e))); }
    ask.disabled = false;
  });

  function show(s) {
    clear(area);
    if (s.candidates.length === 0) { area.append(empty("No suggestions", "There is no sharing history yet to base suggestions on.")); return; }
    area.append(h("div", { class: "chips mb0" },
      badge(s.source === "llm" ? "AI-assisted" : "Rule-based", "blue"), h("span", { class: "muted small" }, "Based on your own sharing history.")));
    const list = h("div", { class: "cands mt" });
    for (const c of s.candidates) list.append(candidate(s, c));
    area.append(list);
  }

  function candidate(s, c) {
    const roles = c.role === "viewer" ? ["read"] : ["read", "edit"];
    const sel = h("select", { "aria-label": `Access for ${c.email}`, value: c.suggested_permission },
      roles.map((r) => h("option", { value: r }, r === "read" ? "Can read" : "Can edit")));
    const controls = h("div", { class: "controls" });
    const el = h("div", { class: "cand" },
      h("div", { class: "who" }, h("strong", null, c.name || "Unknown user"), " ", roleBadge(c.role || ""),
        h("div", { class: "muted small" }, c.email), h("ul", null, c.reasons.map((r) => h("li", null, r)))), controls);
    const decide = async (accept) => {
      try {
        const res = await api(`/documents/${id}/suggestions/${s.id}/decisions`, { method: "POST",
          json: { decisions: [{ user_id: c.user_id, accept, permission: accept ? sel.value : undefined }] } });
        const r = res.results[0];
        if (r.outcome === "error") { toast(r.detail || "Could not share", "error"); return; }
        el.classList.add("done"); clear(controls).append(badge(r.outcome === "accepted" ? "Shared" : "Dismissed", r.outcome === "accepted" ? "green" : ""));
        if (r.outcome === "accepted") { toast("Shared.", "success"); refreshGrants(); }
      } catch (e) { fail(e); if (e.status === 410) clear(area); }
    };
    controls.append(sel,
      h("button", { class: "btn primary sm", type: "button", onClick: () => decide(true) }, "Share"),
      h("button", { class: "btn sm", type: "button", onClick: () => decide(false) }, "Dismiss"));
    return el;
  }
}
