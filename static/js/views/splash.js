import { h, reducedMotion } from "../ui.js";
import { shieldMark } from "../icons.js";

// The animated "TrustVault" intro. Click or press any key to skip. Skipped entirely for reduced-motion users.
export function showSplash(host) {
  return new Promise((resolve) => {
    if (reducedMotion()) { resolve(); return; }
    const word = (text, cls) => text.split("").map((c, i) => {
      const s = h("span", { class: cls }, c);
      s.style.setProperty("--i", String(i + (cls ? 5 : 0)));
      return s;
    });
    const splash = h("div", { class: "splash", role: "presentation" },
      h("div", { class: "orb o1" }), h("div", { class: "orb o2" }), h("div", { class: "orb o3" }), h("div", { class: "grid-bg" }),
      shieldMark(112),
      h("div", { class: "wordmark", "aria-label": "TrustVault" }, word("Trust", ""), word("Vault", "vault")),
      h("div", { class: "tagline" }, "Secure document sharing · Provable access"),
      h("div", { class: "splash-bar" }, h("i")),
      h("div", { class: "skip" }, "Click anywhere to skip"));
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      document.removeEventListener("keydown", finish);
      splash.classList.add("leaving");
      setTimeout(() => { splash.remove(); resolve(); }, 600);
    };
    splash.addEventListener("click", finish);
    document.addEventListener("keydown", finish);
    host.append(splash);
    setTimeout(finish, 4300);
  });
}
