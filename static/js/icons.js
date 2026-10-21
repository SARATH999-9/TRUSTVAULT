// Tiny inline icon set (stroke icons, 24x24), created with createElementNS so no HTML strings are involved.
const NS = "http://www.w3.org/2000/svg";
const P = {
  shield: ["M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  user: ["M12 12a4 4 0 100-8 4 4 0 000 8z", "M4 21c0-4 4-6 8-6s8 2 8 6"],
  users: ["M9 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7z", "M2.5 20c0-3.6 2.9-5.5 6.5-5.5s6.5 1.9 6.5 5.5", "M16 4.5a3.5 3.5 0 010 6.5", "M18 14.8c2 .6 3.5 2.2 3.5 5.2"],
  lock: ["M6 11h12v9H6z", "M8.5 11V8a3.5 3.5 0 017 0v3"],
  file: ["M7 3h7l5 5v13H7z", "M14 3v5h5"],
  upload: ["M12 16V4", "M7 9l5-5 5 5", "M5 20h14"],
  download: ["M12 4v12", "M7 11l5 5 5-5", "M5 20h14"],
  eye: ["M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z", "M12 9a3 3 0 100 6 3 3 0 000-6z"],
  clock: ["M12 3a9 9 0 100 18 9 9 0 000-18z", "M12 7v5l3 2"],
  x: ["M6 6l12 12", "M18 6L6 18"],
  plus: ["M12 5v14", "M5 12h14"],
  pen: ["M4 20l4-1 11-11-3-3L5 16z", "M14 6l3 3"],
  chart: ["M4 20V10", "M10 20V4", "M16 20v-8", "M3 20h18"],
  sliders: ["M4 7h9", "M17 7h3", "M4 17h3", "M11 17h9", "M13 5v4", "M7 15v4"],
  alert: ["M12 3.5l9.5 16.5h-19z", "M12 10v4.5", "M12 17.5h.01"],
  share: ["M4 12v8h16v-8", "M12 15V3", "M7.5 7.5L12 3l4.5 4.5"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6.5 7l1 13h9l1-13"],
  grid: ["M4 4h7v7H4z", "M13 4h7v7h-7z", "M4 13h7v7H4z", "M13 13h7v7h-7z"],
  logout: ["M9 4H5v16h4", "M16 8l4 4-4 4", "M20 12H9"],
  mail: ["M3 6h18v12H3z", "M3.5 7l8.5 6.5L20.5 7"],
  building: ["M4 21V4h10v17", "M14 9h6v12", "M8 8h2", "M8 12h2", "M8 16h2", "M2 21h20"],
  hourglass: ["M6 3h12", "M6 21h12", "M7 3c0 5 5 6 5 9s-5 4-5 9", "M17 3c0 5-5 6-5 9s5 4 5 9"],
  refresh: ["M20 11a8 8 0 10-2.3 5.7", "M20 4v7h-7"],
  list: ["M8 6h12", "M8 12h12", "M8 18h12", "M4 6h.01", "M4 12h.01", "M4 18h.01"],
  history: ["M3 12a9 9 0 109-9 9 9 0 00-6.4 2.6L3 8", "M3 3v5h5", "M12 7v5l3 2"],
  star: ["M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"],
};
const G = [["#4285F4", "M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"],
  ["#34A853", "M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0012 23z"],
  ["#FBBC05", "M5.84 14.09a6.6 6.6 0 010-4.18V7.07H2.18a11 11 0 000 9.86l3.66-2.84z"],
  ["#EA4335", "M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z"]];

export function svg(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  for (const k of kids) if (k) el.append(k);
  return el;
}

export function icon(name, size = 20, cls = "") {
  const root = svg("svg", { viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
    "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: `icon ${cls}`.trim() });
  if (name === "google") {
    root.setAttribute("fill", "currentColor"); root.setAttribute("stroke", "none");
    for (const [fill, d] of G) root.append(svg("path", { d, fill }));
    return root;
  }
  for (const d of P[name] || P.file) root.append(svg("path", { d }));
  return root;
}

// The animated brand mark: a shield that draws itself, then the check mark.
export function shieldMark(size = 120) {
  const root = svg("svg", { viewBox: "0 0 64 64", width: size, height: size, class: "shield-mark", "aria-hidden": "true" });
  root.append(svg("path", { class: "shield-body", d: "M32 6l22 8v16c0 14-9 24-22 28C19 54 10 44 10 30V14z", fill: "none", stroke: "currentColor", "stroke-width": "2.5", "stroke-linejoin": "round" }));
  root.append(svg("path", { class: "shield-fill", d: "M32 6l22 8v16c0 14-9 24-22 28C19 54 10 44 10 30V14z" }));
  root.append(svg("path", { class: "shield-check", d: "M22 32l7 7 14-15", fill: "none", stroke: "#fff", "stroke-width": "4.5", "stroke-linecap": "round", "stroke-linejoin": "round" }));
  return root;
}
