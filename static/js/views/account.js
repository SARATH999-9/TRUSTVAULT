import { api } from "../api.js";
import { h, card, field, pageHeader, roleBadge, statusBadge, providerBadge, fmtDate, toast, errMsg, notice } from "../ui.js";

export async function renderAccount(root, ctx) {
  const { me } = ctx;
  root.append(pageHeader("My account", "Your profile and sign-in security."));
  root.append(card("Profile", h("dl", { class: "kv" },
    h("dt", null, "Name"), h("dd", null, me.name), h("dt", null, "Email"), h("dd", null, me.email),
    h("dt", null, "Role"), h("dd", null, roleBadge(me.role)), h("dt", null, "Status"), h("dd", null, statusBadge(me.status)),
    h("dt", null, "Sign-in method"), h("dd", null, me.auth_provider === "google" ? "Google" : "Email and password", " ", providerBadge(me)),
    h("dt", null, "Member since"), h("dd", null, fmtDate(me.created_at)))));

  if (me.auth_provider === "google") {
    root.append(card("Password", notice("You sign in with Google, so there is no TrustVault password to change. Manage your password and two-step verification in your Google account.", "")));
    return;
  }
  const current = h("input", { type: "password", required: true, autocomplete: "current-password", maxLength: 128 });
  const next = h("input", { type: "password", required: true, minLength: 10, maxLength: 128, autocomplete: "new-password" });
  const error = h("div", { class: "form-error", hidden: true, role: "alert" });
  const submit = h("button", { class: "btn primary", type: "submit" }, "Change password");
  const form = h("form", { class: "tight" }, error, field("Current password", current), field("New password", next, "At least 10 characters."), submit);
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); error.hidden = true; submit.disabled = true;
    try {
      await api("/auth/change-password", { method: "POST", json: { current_password: current.value, new_password: next.value } });
      toast("Password changed. Your other sessions were signed out.", "success");
      form.reset();
    } catch (err) { error.textContent = errMsg(err); error.hidden = false; }
    submit.disabled = false;
  });
  root.append(card("Change password", form));
}
