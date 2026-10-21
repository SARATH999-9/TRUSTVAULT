import { api } from "../api.js";
import { h, clear, field, errMsg, icon } from "../ui.js";
import { shieldMark } from "../icons.js";

const PORTALS = [
  { key: "admin", title: "Administrator", icon: "shield", signup: false,
    blurb: "Approve people, review uploads, set the upload rules and watch the audit trail." },
  { key: "owner", title: "Owner", icon: "building", signup: true,
    blurb: "Upload or write documents, share them with approved viewers and take access back at any time." },
  { key: "viewer", title: "Viewer", icon: "eye", signup: true,
    blurb: "Read the documents shared with you, once an administrator has approved your account." },
];
const GIS = "https://accounts.google.com/gsi/client";

function loadGoogle() {
  if (window.google && window.google.accounts && window.google.accounts.id) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = GIS; s.async = true; s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Google sign-in could not be loaded"));
    document.head.append(s);
  });
}

function strength(pw) {
  let s = 0;
  if (pw.length >= 10) s++;
  if (pw.length >= 14) s++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw) && /\d/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  return pw.length ? Math.max(1, s) : 0;
}

function passwordInput(props) {
  const input = h("input", { type: "password", required: true, maxLength: 128, ...props });
  const toggle = h("button", { class: "pw-toggle", type: "button", "aria-label": "Show or hide password" }, "Show");
  toggle.addEventListener("click", () => { const show = input.type === "password"; input.type = show ? "text" : "password"; toggle.textContent = show ? "Hide" : "Show"; });
  return { input, node: h("div", { class: "pw-wrap" }, input, toggle) };
}

export function renderAuth(root, ctx) {
  const main = h("div", { class: "auth-main" });
  clear(root).append(h("div", { class: "auth" },
    h("div", { class: "orb o1" }), h("div", { class: "orb o2" }), h("div", { class: "orb o3" }),
    h("div", { class: "auth-top" }, shieldMark(38), "TrustVault"), main));
  showPortals();

  function showPortals() {
    clear(main).append(
      h("div", { class: "auth-title" }, h("h1", null, "Choose your portal"),
        h("p", null, "Confidential documents, shared only with the people you approve — with a record of everyone who opened them.")),
      h("div", { class: "portals" }, PORTALS.map((p) => h("button", { class: `portal ${p.key}`, type: "button", onClick: () => showForm(p, "signin") },
        h("div", { class: "badge-ic" }, icon(p.icon, 26)), h("h2", null, p.title), h("p", null, p.blurb),
        h("span", { class: "go" }, "Continue", icon("check", 16))))),
      h("div", { class: "trust-row" },
        h("span", null, icon("lock", 16), "Every request checked on the server"),
        h("span", null, icon("history", 16), "Tamper-evident audit trail"),
        h("span", null, icon("users", 16), "Admin-approved accounts")));
  }

  function showForm(portal, mode) {
    const error = h("div", { class: "form-error", hidden: true, role: "alert" });
    const body = h("div");
    const show = (m) => { error.hidden = true; mode = m; draw(); };
    const tabs = portal.signup ? h("div", { class: "tabs", role: "tablist" },
      [["signin", "Sign in"], ["signup", "Create account"]].map(([k, l]) => h("button", { class: `tab ${k === mode ? "active" : ""}`, type: "button", role: "tab", onClick: () => show(k) }, l))) : null;
    const card = h("div", { class: "auth-card" },
      h("button", { class: "back", type: "button", onClick: showPortals }, "← All portals"),
      h("div", { class: `portal-head ${portal.key}` }, h("div", { class: "badge-ic" }, icon(portal.icon, 22)),
        h("div", null, h("h2", null, `${portal.title} portal`), h("p", null, portal.signup ? "Sign in, or request an account." : "Administrator accounts are created by the system owner."))),
      tabs, error, body);
    clear(main).append(card);

    const fail = (e) => { error.textContent = typeof e === "string" ? e : errMsg(e); error.hidden = false; };
    function draw() {
      if (tabs) [...tabs.children].forEach((t, i) => t.classList.toggle("active", (i === 0) === (mode === "signin")));
      clear(body).append(mode === "signin" ? signinForm() : signupForm(), divider(), googleArea(), mode === "signup"
        ? h("p", { class: "fine" }, "An administrator reviews every new account. You will see a waiting screen until you are approved.") : null);
    }
    const divider = () => h("div", { class: "divider" }, "or");

    function signinForm() {
      const email = h("input", { type: "email", name: "email", required: true, autocomplete: "username", maxLength: 254 });
      const pw = passwordInput({ name: "password", autocomplete: "current-password" });
      const submit = h("button", { class: "btn primary", type: "submit" }, "Sign in");
      const f = h("form", { class: "tight" }, field("Email", email), field("Password", pw.node), submit);
      f.addEventListener("submit", async (e) => {
        e.preventDefault(); error.hidden = true; submit.disabled = true;
        try { const res = await api("/auth/login", { method: "POST", json: { email: email.value, password: pw.input.value, portal: portal.key } }); ctx.onLogin(res.user); }
        catch (err) { fail(err); submit.disabled = false; pw.input.value = ""; pw.input.focus(); }
      });
      setTimeout(() => email.focus(), 30);
      return f;
    }

    function signupForm() {
      const name = h("input", { type: "text", name: "name", required: true, minLength: 2, maxLength: 120, autocomplete: "name" });
      const email = h("input", { type: "email", name: "email", required: true, autocomplete: "email", maxLength: 254 });
      const pw = passwordInput({ name: "password", minLength: 10, autocomplete: "new-password" });
      const again = passwordInput({ name: "confirm", minLength: 10, autocomplete: "new-password" });
      const meter = h("div", { class: "strength" }, h("i"), h("i"), h("i"), h("i"));
      pw.input.addEventListener("input", () => { meter.className = `strength s${strength(pw.input.value)}`; });
      const submit = h("button", { class: "btn primary", type: "submit" }, `Request ${portal.title.toLowerCase()} account`);
      const pwField = field("Password", pw.node, "At least 10 characters. Longer is stronger.");
      pwField.append(meter);
      const f = h("form", { class: "tight" }, field("Full name", name), field("Email", email), pwField, field("Confirm password", again.node), submit);
      f.addEventListener("submit", async (e) => {
        e.preventDefault(); error.hidden = true;
        if (pw.input.value !== again.input.value) { fail("Passwords do not match"); return; }
        submit.disabled = true;
        try { const res = await api("/auth/register", { method: "POST", json: { name: name.value, email: email.value, password: pw.input.value, role: portal.key } }); ctx.onLogin(res.user); }
        catch (err) { fail(err); submit.disabled = false; }
      });
      setTimeout(() => name.focus(), 30);
      return f;
    }

    function googleArea() {
      const slot = h("div", { class: "google-slot" });
      if (!ctx.config.google_client_id) {
        slot.append(h("button", { class: "btn google-btn", type: "button", disabled: true, title: "The server administrator has not set GOOGLE_CLIENT_ID yet" },
          icon("google", 20), "Continue with Google"));
        return h("div", null, slot, h("p", { class: "fine" }, "Google sign-in is not enabled on this server yet."));
      }
      loadGoogle().then(() => {
        window.google.accounts.id.initialize({
          client_id: ctx.config.google_client_id, ux_mode: "popup", auto_select: false,
          callback: async (resp) => {
            error.hidden = true;
            try { const res = await api("/auth/google", { method: "POST", json: { credential: resp.credential, portal: portal.key } }); ctx.onLogin(res.user); }
            catch (err) { fail(err); }
          },
        });
        window.google.accounts.id.renderButton(slot, { theme: "outline", size: "large", text: "continue_with", shape: "pill", width: 340 });
      }).catch(() => slot.append(h("p", { class: "fine" }, "Google sign-in could not load. Check your connection or ad blocker.")));
      return slot;
    }
    draw();
  }
}
