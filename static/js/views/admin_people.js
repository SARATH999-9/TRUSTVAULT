import { api } from "../api.js";
import { h, clear, toast, errMsg, formModal, confirmDialog, pageHeader, card, skeleton, empty, notice, badge, roleBadge, statusBadge,
  providerBadge, fmtDate, table, field, avatar, icon, fmtBytes } from "../ui.js";

const fail = (e) => toast(errMsg(e), "error");
const changed = () => window.dispatchEvent(new Event("tv:changed"));
const patch = (id, json) => api(`/admin/users/${id}`, { method: "PATCH", json });

// Asks the admin for a reason, then applies a status change (reject / suspend).
function withReason({ title, verb, status, user, done }) {
  formModal({
    title, submitLabel: verb, danger: true,
    intro: `${user.name} <${user.email}> will ${status === "rejected" ? "be declined" : "be signed out everywhere and lose access"}. They will see the reason you give.`,
    fields: [{ name: "reason", label: "Reason", type: "textarea", maxLength: 500, required: true, placeholder: "e.g. We could not match this request to a known customer" }],
    onSubmit: async (v) => { await patch(user.id, { status, reason: v.reason.trim() }); toast(`${user.name}: ${status}.`, "success"); changed(); done(); },
  });
}

/* ---------- approvals queue ---------- */
export async function renderApprovals(root) {
  root.append(pageHeader("Approvals", "People who asked for an account. Nobody gets access until you approve them."));
  const queue = h("div"), recent = h("div");
  root.append(queue, h("div", { class: "mt" }), recent);

  async function load() {
    clear(queue).append(skeleton(3));
    try {
      const [pending, declined] = await Promise.all([api("/admin/users", { params: { status: "pending" } }), api("/admin/users", { params: { status: "rejected", limit: 10 } })]);
      clear(queue).append(card(`Waiting for approval (${pending.length})`, pending.length === 0
        ? empty("No one is waiting", "New sign-ups, including Google sign-ups, will appear here.")
        : h("div", { class: "cands" }, pending.map(person))));
      clear(recent).append(declined.length === 0 ? "" : card("Recently declined", table(["Person", "Role", "Reason", "When", ""], declined.map((u) => [
        h("span", null, u.name, h("div", { class: "muted small" }, u.email)), roleBadge(u.role), u.decision_reason || h("span", { class: "muted" }, "—"), fmtDate(u.decided_at),
        h("button", { class: "btn sm", type: "button", onClick: async () => { try { await patch(u.id, { status: "active" }); toast("Approved.", "success"); changed(); load(); } catch (e) { fail(e); } } }, "Approve instead")]))));
    } catch (e) { clear(queue).append(empty("Could not load approvals", errMsg(e))); }
  }

  function person(u) {
    const role = h("select", { "aria-label": `Role for ${u.email}`, value: u.role }, ["viewer", "owner"].map((r) => h("option", { value: r }, r)));
    const el = h("div", { class: "cand" },
      h("div", { class: "person" }, avatar(u.name), h("div", { class: "meta" }, h("div", { class: "nm" }, u.name), h("div", { class: "em" }, u.email),
        h("div", { class: "chips mt" }, h("span", { class: "muted small" }, "Requested"), roleBadge(u.role), providerBadge(u),
          h("span", { class: "muted small" }, `${fmtDate(u.created_at)}${u.registered_ip ? ` · ${u.registered_ip}` : ""}`)))),
      h("div", { class: "controls" }, h("span", { class: "muted small" }, "Approve as"), role,
        h("button", { class: "btn success sm", type: "button", onClick: async () => {
          try { await patch(u.id, { status: "active", role: role.value }); toast(`${u.name} approved as ${role.value}.`, "success"); changed(); load(); } catch (e) { fail(e); }
        } }, icon("check", 14), "Approve"),
        h("button", { class: "btn danger sm", type: "button", onClick: () => withReason({ title: "Reject account request", verb: "Reject", status: "rejected", user: u, done: load }) }, icon("x", 14), "Reject")));
    return el;
  }
  await load();
}

/* ---------- all users ---------- */
export async function renderUsers(root, ctx) {
  const inputs = {
    q: h("input", { type: "search", maxLength: 100, placeholder: "Name or email" }),
    status: h("select", null, [["", "Any status"], ["pending", "Pending"], ["active", "Active"], ["suspended", "Suspended"], ["rejected", "Rejected"]].map(([v, l]) => h("option", { value: v }, l))),
    role: h("select", null, [["", "Any role"], ["admin", "Admin"], ["owner", "Owner"], ["viewer", "Viewer"]].map(([v, l]) => h("option", { value: v }, l))),
  };
  const box = h("div");
  const form = h("form", { class: "filters" }, field("Search", inputs.q), field("Status", inputs.status), field("Role", inputs.role),
    h("div", { class: "actions" }, h("button", { class: "btn primary", type: "submit" }, "Filter")));
  form.addEventListener("submit", (e) => { e.preventDefault(); load(); });
  root.append(pageHeader("Users", "Every account, its status and role.", h("button", { class: "btn primary", type: "button", onClick: openCreate }, icon("plus", 16), "New user")),
    h("section", { class: "card" }, form), box);

  async function load() {
    clear(box).append(skeleton(5));
    try {
      const users = await api("/admin/users", { params: { q: inputs.q.value.trim(), status: inputs.status.value, role: inputs.role.value } });
      clear(box).append(card(null, users.length === 0 ? empty("No matching users") : table(["Person", "Role", "Status", "Sign-in", "Last sign-in", ""], users.map((u) => {
        const self = u.id === ctx.me.id;
        const role = h("select", { "aria-label": `Role for ${u.email}`, disabled: self, value: u.role }, ["viewer", "owner", "admin"].map((r) => h("option", { value: r }, r)));
        role.addEventListener("change", async () => {
          const ok = await confirmDialog({ title: "Change role?", confirmLabel: "Change role", message: `${u.email} will become ${role.value}. This takes effect immediately.` });
          if (!ok) { role.value = u.role; return; }
          try { await patch(u.id, { role: role.value }); toast("Role updated.", "success"); } catch (e) { fail(e); }
          load();
        });
        const act = (label, cls, status, extra = {}) => h("button", { class: `btn sm ${cls}`, type: "button", onClick: async () => {
          try { await patch(u.id, { status, ...extra }); toast("Updated.", "success"); changed(); load(); } catch (e) { fail(e); } } }, label);
        const actions = self ? [] : u.status === "pending" ? [act("Approve", "success", "active"), h("button", { class: "btn sm danger", type: "button", onClick: () => withReason({ title: "Reject account request", verb: "Reject", status: "rejected", user: u, done: load }) }, "Reject")]
          : u.status === "active" ? [h("button", { class: "btn sm danger", type: "button", onClick: () => withReason({ title: "Suspend account", verb: "Suspend", status: "suspended", user: u, done: load }) }, "Suspend")]
            : [act(u.status === "rejected" ? "Approve" : "Reactivate", "", "active")];
        return [h("span", null, u.name, self ? h("span", { class: "muted" }, " (you)") : null, h("div", { class: "muted small" }, u.email)), role, statusBadge(u.status), providerBadge(u),
          u.last_login_at ? h("span", { class: "nowrap" }, fmtDate(u.last_login_at)) : h("span", { class: "muted" }, "never"), h("div", { class: "row-actions" }, actions)];
      }))));
    } catch (e) { clear(box).append(empty("Could not load users", errMsg(e))); }
  }

  function openCreate() {
    formModal({
      title: "New user", submitLabel: "Create user",
      intro: "Creates an already-approved account. For most people, ask them to sign up instead so they choose their own password.",
      fields: [
        { name: "name", label: "Full name", required: true, maxLength: 120 },
        { name: "email", label: "Email", type: "email", required: true, maxLength: 254, autocomplete: "off" },
        { name: "password", label: "Temporary password", type: "password", required: true, minLength: 10, maxLength: 128, autocomplete: "new-password", help: "At least 10 characters. Share it securely and ask them to change it." },
        { name: "role", label: "Role", type: "select", value: "viewer", options: [
          { value: "viewer", label: "Viewer: reads what is shared with them" }, { value: "owner", label: "Owner: uploads and shares documents" },
          { value: "admin", label: "Admin: manages users and the audit log (no file contents)" }] },
      ],
      onSubmit: async (v) => { await api("/admin/users", { method: "POST", json: v }); toast("User created.", "success"); load(); },
    });
  }
  await load();
}

/* ---------- owners (supervision) ---------- */
export async function renderOwners(root) {
  const owners = await api("/admin/owners");
  root.append(pageHeader("Owners", "Everyone who can upload documents: how much they have uploaded, what is waiting, and a way to freeze their sharing."));
  root.append(notice("Suspending an owner signs them out and immediately stops everyone else from reaching their documents. Reactivating restores access.", ""));
  const box = h("div");
  root.append(box);
  function draw(list) {
    clear(box).append(card(null, list.length === 0 ? empty("No owners yet", "Owners appear here after they sign up and you approve them.") : table(
      ["Owner", "Status", "Documents", "Awaiting", "Approved", "Rejected", "Shares", "Last upload", ""], list.map((o) => [
        h("span", null, o.name, h("div", { class: "muted small" }, o.email)), statusBadge(o.status), o.documents, o.pending ? badge(String(o.pending), "amber") : 0, o.approved,
        o.rejected ? badge(String(o.rejected), "red") : 0, o.shares, o.last_upload ? fmtDate(o.last_upload) : h("span", { class: "muted" }, "never"),
        h("div", { class: "row-actions" }, h("a", { class: "btn sm", href: `#/admin/documents?owner=${encodeURIComponent(o.email)}` }, "Documents"),
          o.status === "active" ? h("button", { class: "btn sm danger", type: "button", onClick: () => withReason({ title: "Suspend owner", verb: "Suspend", status: "suspended", user: o, done: reload }) }, "Suspend")
            : o.status === "pending" ? h("a", { class: "btn sm", href: "#/admin/approvals" }, "Review")
              : h("button", { class: "btn sm", type: "button", onClick: async () => { try { await patch(o.id, { status: "active" }); toast("Reactivated.", "success"); changed(); reload(); } catch (e) { fail(e); } } }, "Reactivate"))]))));
  }
  const reload = async () => { try { draw(await api("/admin/owners")); } catch (e) { fail(e); } };
  draw(owners);
}
