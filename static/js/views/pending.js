import { api } from "../api.js";
import { h, clear, fmtDate, icon, providerBadge, roleBadge, toast, errMsg } from "../ui.js";

let timer = null;
export const stopPolling = () => { if (timer) { clearInterval(timer); timer = null; } };

// Shown to anyone whose account has not been approved yet. The server refuses everything else
// for them, so this screen is purely informational.
export function renderPending(root, ctx) {
  stopPolling();
  const { me } = ctx;
  const check = async (manual) => {
    try {
      const fresh = await api("/auth/me");
      if (fresh.status !== "pending") { stopPolling(); toast("Your account was approved. Welcome!", "success"); ctx.onChange(fresh); }
      else if (manual) toast("Still waiting for an administrator.", "info");
    } catch (e) { if (manual) toast(errMsg(e), "error"); }
  };
  const step = (cls, ic, label) => h("div", { class: `step ${cls}` }, h("div", { class: "dot" }, icon(ic, 16)), label);
  const btn = h("button", { class: "btn primary", type: "button", onClick: () => check(true) }, icon("refresh", 16), "Check status");
  clear(root).append(h("div", { class: "wait" },
    h("div", { class: "orb o1" }), h("div", { class: "orb o2" }),
    h("div", { class: "card" },
      h("div", { class: "pulse" }, h("i"), h("i"), h("i"), h("div", { class: "core" }, icon("hourglass", 34))),
      h("h1", null, "Waiting for admin approval"),
      h("p", { class: "muted" }, `Thanks, ${me.name.split(" ")[0]}. An administrator needs to approve your ${me.role} account before you can use TrustVault. This page updates by itself.`),
      h("div", { class: "stepper" }, step("done", "check", "Account created"), step("now", "clock", "Admin review"), step("", "lock", "Access granted")),
      h("dl", { class: "kv facts" },
        h("dt", null, "Name"), h("dd", null, me.name), h("dt", null, "Email"), h("dd", null, me.email),
        h("dt", null, "Requested role"), h("dd", null, roleBadge(me.role)), h("dt", null, "Identity"), h("dd", null, providerBadge(me)),
        h("dt", null, "Submitted"), h("dd", null, fmtDate(me.created_at))),
      h("div", { class: "actions" }, btn,
        h("button", { class: "btn", type: "button", onClick: () => { stopPolling(); ctx.onLogout(); } }, "Sign out")))));
  timer = setInterval(() => check(false), 8000);
}
