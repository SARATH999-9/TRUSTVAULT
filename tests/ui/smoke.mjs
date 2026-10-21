// Drives the REAL front-end (bundled from static/js) in jsdom against a live TrustVault server, as every kind of person.
import { JSDOM, VirtualConsole } from "jsdom";
import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8770";
const ADMIN = { email: "admin@uitest.local", password: "Admin-Password-1234" };
const PW = "a-long-password-1";
const here = path.dirname(fileURLToPath(import.meta.url));
const bundle = (await build({ entryPoints: [path.join(here, "../../static/js/main.js")], bundle: true, format: "iife", write: false })).outputFiles[0].text;
const html = await (await fetch(`${BASE}/`)).text();

let passed = 0, failed = 0;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ok = (cond, msg) => { if (cond) { passed++; console.log(`  ok   ${msg}`); } else { failed++; console.log(`  FAIL ${msg}`); } };

async function openApp(label, { google = true } = {}) {
  const jar = new Map(), calls = [], errors = [], google_ = { cfg: null, rendered: 0 };
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e.message || e)));
  const dom = new JSDOM(html, { url: `${BASE}/`, runScripts: "outside-only", pretendToBeVisual: true, virtualConsole: vc });
  const w = dom.window;
  w.URL.createObjectURL = () => "blob:test"; w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = function () { calls.push(`CLICK-DOWNLOAD ${this.download}`); };
  if (google) w.google = { accounts: { id: { initialize: (c) => { google_.cfg = c; }, renderButton: (el) => { google_.rendered++; el.setAttribute("data-google-rendered", "1"); } } } };
  w.fetch = async (input, opts = {}) => {
    const url = new URL(input, `${BASE}/`), method = (opts.method || "GET").toUpperCase();
    const headers = new Headers(opts.headers || {});
    if (jar.size) headers.set("cookie", [...jar].map(([k, v]) => `${k}=${v}`).join("; "));
    if (method !== "GET" && method !== "HEAD") headers.set("origin", BASE);
    let body = opts.body;
    if (body instanceof w.FormData) {
      const nf = new FormData();
      for (const [k, v] of body.entries()) {
        if (typeof v === "string") nf.append(k, v);
        else nf.append(k, new Blob([await new Promise((r) => { const fr = new w.FileReader(); fr.onload = () => r(fr.result); fr.readAsArrayBuffer(v); })]), v.name);
      }
      body = nf;
    }
    const res = await fetch(url, { method, headers, body, redirect: "manual" });
    for (const sc of res.headers.getSetCookie()) {
      const [pair, ...attrs] = sc.split(";"); const [k, v] = pair.split("=");
      if (attrs.some((a) => /max-age=0/i.test(a)) || v === "") jar.delete(k.trim()); else jar.set(k.trim(), v);
    }
    calls.push(`${method} ${url.pathname} ${res.status}`);
    return res;
  };
  w.eval(bundle);
  const d = w.document;
  const a = {
    w, d, calls, errors, label, google: google_, jar,
    text: () => d.body.textContent,
    q: (s) => d.querySelector(s), qa: (s) => [...d.querySelectorAll(s)],
    byText: (sel, t) => [...d.querySelectorAll(sel)].find((e) => e.textContent.trim().includes(t)),
    async waitFor(fn, msg, ms = 9000) {
      const end = Date.now() + ms;
      while (Date.now() < end) { try { const v = fn(); if (v) return v; } catch { /* retry */ } await sleep(25); }
      throw new Error(`timeout waiting for: ${msg}\n--- page text ---\n${d.body.textContent.slice(0, 500)}`);
    },
    submit(form) { form.dispatchEvent(new w.Event("submit", { cancelable: true, bubbles: true })); },
    set(el, v) { el.value = v; el.dispatchEvent(new w.Event("input", { bubbles: true })); el.dispatchEvent(new w.Event("change", { bubbles: true })); },
    fill(form, values) { for (const [k, v] of Object.entries(values)) a.set(form.querySelector(`[name=${k}]`), v); },
    click(el) { el.dispatchEvent(new w.MouseEvent("click", { bubbles: true, cancelable: true })); },
    nav(hash) { w.location.hash = hash; },
    async visit(hash, heading) {                      // always re-renders, even if we are already on that page
      if (w.location.hash === hash) { w.location.hash = "#/account"; await sleep(80); }
      w.location.hash = hash;
      if (heading) await a.waitFor(() => a.byText("h1", heading), `page "${heading}"`);
    },
    toasts: () => (d.getElementById("toasts") || { textContent: "" }).textContent,
    async skipIntro() { await a.waitFor(() => a.q(".splash"), "splash"); a.click(a.q(".splash")); await a.waitFor(() => a.q(".portals"), "portal chooser"); },
    async portal(name) { await a.waitFor(() => a.q(`.portal.${name}`), `${name} portal`); a.click(a.q(`.portal.${name}`)); await a.waitFor(() => a.q(".auth-card"), "portal form"); },
    async signIn(portal, email, password) {
      if (!a.q(".auth-card")) { if (!a.q(".portals")) await a.skipIntro(); await a.portal(portal); }
      a.fill(a.q(".auth-card form"), { email, password }); a.submit(a.q(".auth-card form"));
    },
    async signUp(portal, name, email) {
      await a.skipIntro(); await a.portal(portal);
      a.click(a.byText(".tab", "Create account"));
      await a.waitFor(() => a.q("input[name=confirm]"), "sign-up form");
      a.fill(a.q(".auth-card form"), { name, email, password: PW, confirm: PW }); a.submit(a.q(".auth-card form"));
    },
    async modal(fn) { const f = await a.waitFor(() => a.q(".modal form"), "modal form"); fn(f); a.submit(f); },
    async closeModal() { a.q(".modal .x") && a.click(a.q(".modal .x")); },
  };
  return a;
}

async function section(name, fn) { console.log(`\n${name}`); try { await fn(); } catch (e) { failed++; console.log(`  FAIL ${e.message}`); } }
const PDF = new TextEncoder().encode("%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n");
const pdfFile = (w, name) => new w.File([PDF], name, { type: "application/pdf" });

const apps = {};
const ts = Date.now().toString(36);
const E = { owner: `olivia.${ts}@example.com`, viewer: `victor.${ts}@example.com`, nope: `nora.${ts}@example.com` };

/* ======================= 1. intro + portals ======================= */
await section("Animated intro and the three portals", async () => {
  const a = await openApp("anon");
  const splash = await a.waitFor(() => a.q(".splash"), "animated splash");
  ok(splash.textContent.replace(/\s/g, "").includes("TrustVault"), "the TrustVault wordmark animates in on first load");
  ok(a.qa(".wordmark span").length === 10 && a.q(".shield-mark") && a.q(".splash-bar"), "shield, ten animated letters and a progress bar are present");
  a.click(splash);
  await a.waitFor(() => a.q(".portals"), "portal chooser");
  ok(!a.q(".splash"), "the intro can be skipped with a click and then disappears");
  ok(a.qa(".portal").length === 3, "three portals are offered");
  ok(["Administrator", "Owner", "Viewer"].every((t) => a.byText(".portal h2", t)), "Administrator, Owner and Viewer portals");
  ok(a.text().includes("Admin-approved accounts") && a.text().includes("Tamper-evident audit trail"), "trust points are shown");
  ok(a.errors.length === 0, `no script errors (${a.errors.join("; ")})`);
  apps.anon = a;
});

/* ======================= 2. admin portal ======================= */
await section("Administrator portal", async () => {
  const a = apps.anon;
  await a.portal("admin");
  ok(!a.q(".auth-card .tabs"), "no 'Create account' for administrators (they are created by the system owner)");
  await a.waitFor(() => a.q("[data-google-rendered]"), "Google button");
  ok(a.google.cfg && a.google.cfg.client_id === "ui-test.apps.googleusercontent.com", "Google sign-in is initialised with the server's client id");
  a.google.cfg.callback({ credential: "not-a-real-google-token-at-all" });
  await a.waitFor(() => a.q(".form-error") && !a.q(".form-error").hidden, "google refusal");
  ok(/Google could not verify/.test(a.q(".form-error").textContent), "a forged Google token is refused by the server and the user is told");
  await a.signIn("admin", ADMIN.email, "wrong-password-123");
  await a.waitFor(() => a.q(".form-error") && !a.q(".form-error").hidden && /Invalid email or password/.test(a.q(".form-error").textContent), "bad password message");
  ok(true, "wrong password shows one generic message");
  a.click(a.byText(".back", "All portals"));
  await a.portal("owner");
  a.fill(a.q(".auth-card form"), { email: ADMIN.email, password: ADMIN.password }); a.submit(a.q(".auth-card form"));
  await a.waitFor(() => /Admin portal/.test((a.q(".form-error") || {}).textContent || ""), "wrong portal");
  ok(true, "signing in at the wrong portal is refused and points to the right one");
  a.click(a.byText(".back", "All portals"));
  await a.portal("admin");
  a.fill(a.q(".auth-card form"), { email: ADMIN.email, password: ADMIN.password }); a.submit(a.q(".auth-card form"));
  await a.waitFor(() => a.byText("h1", "Overview"), "admin overview");
  ok(a.byText("h2", "Nothing is waiting for you"), "empty system: nothing waiting for approval");
  ok(["Approvals", "Document review", "Users", "Owners", "Upload policy", "Alerts", "Audit log"].every((t) => a.byText(".nav a", t)), "full administrator navigation");
  ok(!a.byText(".nav a", "My documents"), "administrators have no document workspace");
  apps.admin = a;
});

/* ======================= 3. sign-ups and the waiting room ======================= */
await section("Owner and viewer sign up and wait for approval", async () => {
  const o = await openApp("owner"); apps.owner = o;
  await o.signUp("owner", "Olivia Owner", E.owner);
  await o.waitFor(() => o.byText("h1", "Waiting for admin approval"), "waiting room");
  ok(o.q(".pulse") && o.q(".stepper") && o.text().includes("Admin review"), "animated waiting screen with a progress tracker");
  ok(o.text().includes(E.owner) && o.text().includes("Email not verified"), "shows who is waiting and that the email is unverified");
  o.nav("#/documents"); await sleep(250);
  ok(o.byText("h1", "Waiting for admin approval") && !o.q(".nav"), "typing another URL does not get past the waiting room");
  o.click(o.byText("button", "Check status"));
  await o.waitFor(() => /Still waiting/.test(o.toasts()), "still-waiting toast");
  ok(true, "'Check status' reports they are still waiting");

  const v = await openApp("viewer"); apps.viewer = v;
  await v.signUp("viewer", "Victor Viewer", E.viewer);
  await v.waitFor(() => v.byText("h1", "Waiting for admin approval"), "viewer waiting room");
  ok(v.text().includes("viewer account"), "viewer is told which account type was requested");

  const n = await openApp("nope"); apps.nope = n;
  await n.signUp("viewer", "Nora Nope", E.nope);
  await n.waitFor(() => n.byText("h1", "Waiting for admin approval"), "third waiting room");

  const dup = await openApp("dup");
  await dup.skipIntro(); await dup.portal("viewer"); dup.click(dup.byText(".tab", "Create account"));
  await dup.waitFor(() => dup.q("input[name=confirm]"), "form");
  dup.fill(dup.q(".auth-card form"), { name: "Copy Cat", email: E.viewer.toUpperCase(), password: PW, confirm: PW }); dup.submit(dup.q(".auth-card form"));
  await dup.waitFor(() => /already exists/.test((dup.q(".form-error") || {}).textContent || ""), "duplicate");
  ok(true, "a duplicate email (any case) is refused");
  dup.click(dup.byText(".tab", "Create account"));
  dup.fill(dup.q(".auth-card form"), { name: "Copy Cat", email: "copy@example.com", password: PW, confirm: "different-password-9" }); dup.submit(dup.q(".auth-card form"));
  await dup.waitFor(() => /do not match/.test((dup.q(".form-error") || {}).textContent || ""), "mismatch");
  ok(true, "mismatched passwords are caught before sending");
});

/* ======================= 4. admin approvals ======================= */
await section("Administrator approves, rejects and sees the details", async () => {
  const a = apps.admin;
  a.nav("#/admin/approvals");
  await a.waitFor(() => a.byText("h2", "Waiting for approval (3)"), "three people waiting");
  ok(a.byText(".cand", E.owner) && a.byText(".cand", "Olivia Owner"), "pending people are listed with their details");
  ok(a.byText(".cand", "Email not verified") && /\d+\.\d+\.\d+\.\d+/.test(a.byText(".cand", E.owner).textContent), "…including whether the email is verified, when they signed up and from which IP");
  await a.waitFor(() => { const b = a.q("[data-badge=users]"); return b && !b.hidden && b.textContent === "3"; }, "sidebar badge");
  ok(true, "the sidebar shows a live count of accounts waiting");
  a.click(a.byText(".cand", E.owner).querySelector(".success"));
  await a.waitFor(() => a.byText("h2", "Waiting for approval (2)"), "owner approved");
  a.click(a.byText(".cand", E.viewer).querySelector(".success"));
  await a.waitFor(() => a.byText("h2", "Waiting for approval (1)"), "viewer approved");
  a.click(a.byText(".cand", E.nope).querySelector(".danger"));
  await a.modal((f) => a.fill(f, { reason: "Could not match this request to a customer" }));
  await a.waitFor(() => a.byText("h2", "Waiting for approval (0)") && a.byText("h2", "Recently declined"), "declined listed");
  ok(a.text().includes("Could not match this request to a customer"), "a rejection reason is required and recorded");
  await a.waitFor(() => { const b = a.q("[data-badge=users]"); return b && b.hidden; }, "badge cleared");
  ok(true, "the badge clears when the queue is empty");
});

await section("Approved people get in; rejected people are told why", async () => {
  const o = apps.owner, v = apps.viewer;
  o.click(o.byText("button", "Check status"));
  await o.waitFor(() => o.byText("h1", "Welcome back") || o.byText("h2", "Welcome back, Olivia"), "owner dashboard");
  ok(o.q(".nav") && o.byText(".nav a", "Write a document"), "owner is let in the moment the admin approves");
  v.click(v.byText("button", "Check status"));
  await v.waitFor(() => v.byText("h1", "Shared with me"), "viewer home");
  ok(v.text().includes("Nothing shared with you yet"), "approved viewer lands on an empty 'Shared with me' list");
  ok(!v.byText(".nav a", "Write a document") && !v.byText("button", "Upload document"), "a viewer has no upload or writing tools");

  const n = await openApp("nope-login");
  await n.skipIntro(); await n.portal("viewer");
  n.fill(n.q(".auth-card form"), { email: E.nope, password: PW }); n.submit(n.q(".auth-card form"));
  await n.waitFor(() => /declined/.test((n.q(".form-error") || {}).textContent || ""), "decline message");
  ok(/Could not match this request/.test(n.q(".form-error").textContent), "a rejected person sees that they were declined, and why");
});

/* ======================= 5. owner works; documents wait for review ======================= */
await section("Owner uploads and writes; everything waits for review", async () => {
  const o = apps.owner;
  o.nav("#/documents");
  await o.waitFor(() => o.byText("h1", "My documents"), "my documents");
  ok(o.text().includes("No documents yet"), "empty state for a new owner");
  o.click(o.byText("button", "Upload document"));
  const f = await o.waitFor(() => o.q(".modal form"), "upload modal");
  ok(/administrator reviews every upload/.test(o.q(".modal").textContent) && /PDF/.test(o.q(".modal").textContent), "upload form shows the admin's rules (types, size, review)");
  Object.defineProperty(f.querySelector("input[type=file]"), "files", { value: [pdfFile(o.w, "Salary letter.pdf")] });
  o.fill(f, { category: "hr", description: "For Victor" }); o.submit(f);
  await o.waitFor(() => o.byText("h1", "Salary letter"), "doc page");
  ok(o.byText(".notice", "Waiting for administrator review"), "owner sees that the upload is waiting for review");
  ok(o.byText(".notice", "Sharing is locked until an administrator approves"), "sharing is locked until approval");
  ok(!o.byText("h2", "Who has access") || !o.q(".inline-form"), "no share form while unapproved");

  o.nav("#/owner/write");
  await o.waitFor(() => o.byText("h1", "Write a document"), "editor");
  const form = o.q("form");
  const inputs = o.qa("form input[type=text]");
  o.set(inputs[0], "<img src=x onerror=alert(1)> Board notes");
  o.set(o.q("textarea.editor"), "Line one\nLine two\n<script>alert(1)</script>");
  o.submit(form);
  await o.waitFor(() => o.byText("h1", "Board notes"), "written doc page");
  ok(o.text().includes("<img src=x onerror=alert(1)>") && !o.q("img[src=x]"), "a hostile title is shown as plain text (no XSS)");
  ok(o.byText("button", "Preview") && o.byText("button", "Edit text"), "written documents offer Preview and Edit text");
  o.click(o.byText("button", "Preview"));
  await o.waitFor(() => o.q(".modal .preview-text"), "preview");
  ok(o.q(".preview-text").textContent.includes("<script>alert(1)</script>") && !o.q(".modal script"), "preview shows the text literally");
  await o.closeModal();
  o.nav("#/owner");
  await o.waitFor(() => o.byText(".stat .label", "Awaiting review"), "dashboard");
  await o.waitFor(() => o.qa(".stat .value").some((e) => e.textContent === "2"), "counts");
  ok(true, "the dashboard counts both documents as awaiting review");
});

await section("Administrator reviews documents (metadata only)", async () => {
  const a = apps.admin;
  a.nav("#/admin/documents");
  await a.waitFor(() => a.byText("h1", "Document review") && a.byText(".tab", "Awaiting review") && a.qa(".cand").length === 2, "two pending");
  ok(a.byText(".notice", "File contents are never shown"), "the admin is told contents are never shown");
  const card = a.byText(".cand", "Salary letter.pdf");
  ok(card.textContent.includes(E.owner) && /sha256 [0-9a-f]{12}/.test(card.textContent) && card.textContent.includes("application/pdf"), "uploader, file type, size and checksum are shown");
  ok(!a.byText("button", "Download") && !a.byText("button", "Preview"), "no way for an administrator to open the file");
  a.click(card.querySelector(".success"));
  await a.waitFor(() => a.qa(".cand").length === 1, "one left");
  a.click(a.q(".cand .danger"));
  await a.modal((f) => a.fill(f, { reason: "Please remove the script tag" }));
  await a.waitFor(() => a.text().includes("Nothing to review"), "queue empty");
  ok(a.text().includes("Nothing to review"), "queue cleared after approve + reject");
  a.click(a.byText(".tab", "Rejected"));
  await a.waitFor(() => a.byText(".cand", "Please remove the script tag"), "rejected tab");
  ok(true, "the rejection and its reason are kept");
});

await section("Owner sees the decisions and can share", async () => {
  const o = apps.owner;
  await o.visit("#/documents", "My documents");
  await o.waitFor(() => o.qa("tbody tr").length === 2, "list");
  ok(o.byText(".badge", "Approved") && o.byText(".badge", "Rejected"), "owner sees Approved and Rejected badges");
  o.click(o.byText("a", "Board notes"));
  await o.waitFor(() => o.byText(".notice", "Rejected by an administrator"), "rejected banner");
  ok(o.byText(".notice", "Please remove the script tag"), "owner is told why it was rejected");
  o.click(o.byText("button", "Edit text"));
  const ef = await o.waitFor(() => o.q(".modal form"), "text editor");
  o.set(ef.querySelector("textarea"), "Corrected text without any script"); o.submit(ef);
  await o.waitFor(() => o.byText(".notice", "Waiting for administrator review"), "back to pending");
  ok(true, "editing creates a new version that goes back to review");
  await o.visit("#/documents", "My documents"); await o.waitFor(() => o.qa("tbody tr").length === 2, "list again");
  o.click(o.byText("a", "Salary letter.pdf"));
  await o.waitFor(() => o.byText(".notice", "Approved by an administrator") && o.q(".inline-form"), "approved doc with share form");
  const share = o.q(".inline-form");
  o.set(share.querySelector("input[type=email]"), "admin@uitest.local"); o.submit(share);
  await o.waitFor(() => /Cannot grant access/.test((o.q(".form-error") || {}).textContent || ""), "refusal");
  ok(true, "an administrator cannot be given access to a document");
  o.set(share.querySelector("input[type=email]"), E.nope); o.submit(share);
  await o.waitFor(() => /Cannot grant access/.test((o.q(".form-error") || {}).textContent || ""), "rejected person refused");
  ok(true, "a person who is not an approved account cannot be given access");
  o.set(share.querySelector("input[type=email]"), E.viewer); o.submit(share);
  await o.waitFor(() => o.byText("td", E.viewer), "viewer listed");
  ok(true, "the approved viewer is shared with");
});

await section("Viewer reads what was shared; the owner stays in control", async () => {
  const v = apps.viewer;
  await v.visit("#/documents", "Shared with me");
  await v.waitFor(() => v.byText("a", "Salary letter.pdf"), "shared doc");
  ok(v.qa("tbody tr").length === 1 && !v.text().includes("Board notes"), "the viewer sees exactly the one approved, shared document");
  v.click(v.byText("a", "Salary letter.pdf"));
  await v.waitFor(() => v.byText("h1", "Salary letter"), "viewer doc page");
  ok(!v.byText("h2", "Who has access") && !v.byText("button", "Delete") && !v.byText("button", "Edit details"), "a viewer cannot manage access, edit or delete");
  v.click(v.byText("button", "Download"));
  await v.waitFor(() => v.calls.some((c) => c.startsWith("CLICK-DOWNLOAD")), "download");
  ok(true, "the viewer can download it");
  const o = apps.owner;
  o.click(o.byText("button", "Revoke"));
  await o.waitFor(() => o.q(".modal"), "confirm"); o.click(o.q(".modal footer .danger.solid"));
  await o.waitFor(() => o.text().includes("Not shared with anyone"), "revoked");
  await v.visit("#/documents", "Shared with me"); await v.waitFor(() => v.text().includes("Nothing shared with you yet"), "list empty");
  ok(true, "after the owner revokes, the viewer's document disappears on their next page");
  o.set(o.q(".inline-form input[type=email]"), E.viewer); o.submit(o.q(".inline-form"));
  await o.waitFor(() => o.byText("td", E.viewer), "re-shared");
});

/* ======================= 6. admin controls ======================= */
await section("Administrator sets the upload policy", async () => {
  const a = apps.admin;
  a.nav("#/admin/policy");
  await a.waitFor(() => a.byText("h1", "Upload policy") && a.qa(".check").length >= 8, "policy form");
  for (const t of ["csv", "png", "jpg", "jpeg"]) a.byText(".check", `.${t}`).querySelector("input").checked = false;
  a.set(a.q("input[type=number]"), "5");
  a.set(a.q("textarea"), "HR\nLegal");
  a.submit(a.q("form"));
  await a.waitFor(() => /Policy saved/.test(a.toasts()), "saved");
  ok(true, "policy saved (types, size, categories)");
  const o = apps.owner;
  await o.visit("#/documents", "My documents");
  o.click(o.byText("button", "Upload document"));
  const f = await o.waitFor(() => o.q(".modal form"), "upload modal");
  ok(!/CSV/.test(o.q(".modal").textContent) && /up to 5 MB/.test(o.q(".modal").textContent), "the upload form now reflects the new rules");
  ok(f.querySelector("select[name=category]") && [...f.querySelector("select[name=category]").options].map((x) => x.value).join() === "HR,Legal", "categories are limited to the admin's list");
  ok(!f.querySelector("input[type=file]").getAttribute("accept").includes(".csv"), "the file picker only offers allowed types");
  await o.closeModal();
});

await section("Administrator supervises owners and suspends one", async () => {
  const a = apps.admin;
  a.nav("#/admin/owners");
  await a.waitFor(() => a.byText("td", E.owner), "owner row");
  const row = a.byText("tr", E.owner);
  ok(/Active/.test(row.textContent) && row.querySelectorAll("td")[2].textContent === "2", "owner directory shows status and document volume");
  a.click(row.querySelector(".danger"));
  await a.modal((f) => a.fill(f, { reason: "Policy investigation" }));
  await a.waitFor(() => a.byText("tr", E.owner) && /Suspended/.test(a.byText("tr", E.owner).textContent), "suspended");
  ok(true, "owner suspended with a reason");
  const v = apps.viewer;
  await v.visit("#/documents", "Shared with me");
  await v.waitFor(() => v.text().includes("Nothing shared with you yet"), "list empty");
  ok(true, "everyone else immediately loses access to a suspended owner's documents");
  const o = apps.owner;
  await o.visit("#/owner");
  await o.waitFor(() => o.q(".auth-card") || o.q(".portals"), "owner signed out");
  ok(true, "the suspended owner is signed out on their next action");
  a.click(a.byText("tr", E.owner).querySelector("button:not(.danger)") || a.byText("button", "Reactivate"));
  await a.waitFor(() => /Active/.test(a.byText("tr", E.owner).textContent), "reactivated");
  ok(true, "and can be reactivated");
});

await section("Audit log and alerts", async () => {
  const a = apps.admin;
  a.nav("#/admin/audit");
  await a.waitFor(() => a.byText("h1", "Audit log") && a.qa("tbody tr").length > 8, "audit rows");
  const actions = new Set(a.qa("tbody tr").map((r) => r.querySelectorAll("td")[3].textContent));
  ok(["register", "login", "upload", "user_update", "document_review", "grant_create", "grant_change"].filter((x) => actions.has(x)).length >= 5, "audit shows sign-ups, approvals, uploads, reviews and sharing");
  ok(a.qa("td .badge").some((b) => b.textContent === "denied"), "refused attempts are in the log");
  a.click(a.byText("button", "Verify audit chain"));
  await a.waitFor(() => a.text().includes("Chain intact"), "verify");
  ok(true, "the audit chain verifies as intact");
  a.nav("#/admin/alerts"); await a.waitFor(() => a.byText("h1", "Alerts"), "alerts");
  ok(true, "alerts page renders");
  a.nav("#/admin"); await a.waitFor(() => a.byText("h1", "Overview") && a.qa(".stat").length === 4, "overview");
  ok(a.byText(".stat .label", "Waiting approval"), "overview shows what is waiting");
});

await section("Access boundaries and sign-out", async () => {
  const v = apps.viewer;
  v.nav("#/admin/approvals"); await sleep(400);
  ok(!v.byText("h1", "Approvals") && /do not have access/.test(v.toasts()), "a viewer typing an admin URL is turned away");
  const a = apps.admin;
  a.nav("#/documents"); await sleep(400);
  ok(!a.byText("h1", "My documents"), "administrators cannot open the document workspace");
  a.click(a.byText("button", "Sign out"));
  await a.waitFor(() => a.q(".portals") || a.q(".auth"), "signed out");
  a.nav("#/admin"); await sleep(300);
  ok(!a.q(".nav") && a.q(".auth"), "after sign-out the admin screens are unreachable");
  for (const k of Object.keys(apps)) ok(apps[k].errors.length === 0, `${k}: no script errors (${apps[k].errors.join("; ")})`);
});

console.log(`\n${passed} checks passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
