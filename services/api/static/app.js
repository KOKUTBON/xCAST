// xCAST — Studio front end.
// Plain ES module, no build step. Server-provided text is only ever inserted
// through textContent / value, never as HTML.

/* =========================================================================
   Utilities
   ========================================================================= */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const SVG_NS = "http://www.w3.org/2000/svg";
const JOB_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{2,79}$/;
const WORDS_PER_SECOND = 2.6; // matches the worker's SRT timing estimate
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

function icon(name, cls = "icon") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

/** Tiny element builder: h("div", { class: "x", onclick }, "text", child) */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key in el && typeof value !== "string") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw == null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable — non-essential */
    }
  },
};

const fmtBytes = (n) => {
  if (n == null || Number.isNaN(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
};
const fmtClock = (secs) => {
  if (!Number.isFinite(secs) || secs < 0) secs = 0;
  const s = Math.floor(secs % 60);
  const m = Math.floor((secs / 60) % 60);
  const hrs = Math.floor(secs / 3600);
  const mm = hrs ? String(m).padStart(2, "0") : String(m);
  return `${hrs ? `${hrs}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
};
const fmtTimeOfDay = (iso) => {
  const d = iso ? new Date(iso) : new Date();
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};
const relTime = (iso) => {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = (Date.now() - t) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
};
const wordCount = (text) => (String(text || "").trim().match(/\S+/g) || []).length;
const isTyping = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const STATUS_LABEL = {
  idle: "Idle",
  queued: "Queued",
  running: "Running",
  awaiting_review: "Needs review",
  succeeded: "Complete",
  failed: "Failed",
};
const STATUS_VAR = {
  queued: "--amber",
  running: "--ember",
  awaiting_review: "--violet",
  succeeded: "--ok",
  failed: "--danger",
};
const STYLE_LABEL = {
  everyday: "Everyday",
  academic: "Academic",
  energetic_academic: "Energetic academic",
  authoritative: "Authoritative",
};
const TERMINAL = new Set(["succeeded", "failed"]);

function statusBadge(status, small = false) {
  const s = status || "idle";
  return h(
    "span",
    { class: `status-badge${small ? " sm" : ""}`, dataset: { status: s } },
    h("span", { class: "sb-dot" }),
    STATUS_LABEL[s] || s,
  );
}

/* =========================================================================
   Toasts
   ========================================================================= */
function toast(message, tone = "ok") {
  const host = $("[data-toasts]");
  const el = h("div", { class: `toast${tone === "error" ? " is-error" : ""}`, role: tone === "error" ? "alert" : "status" },
    icon(tone === "error" ? "alert" : "check"), h("span", { text: message }));
  host.append(el);
  setTimeout(() => {
    el.classList.add("is-out");
    setTimeout(() => el.remove(), 240);
  }, tone === "error" ? 6000 : 3600);
}

/* =========================================================================
   API client
   ========================================================================= */
const state = { apiKey: "", conn: "unknown" };

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const DEFAULT_ERRORS = {
  0: "Can't reach the API. Is the server running?",
  401: "This server requires an API key.",
  404: "Not found.",
  409: "That conflicts with an existing job.",
  413: "That file is over the server's upload limit.",
  415: "Only PDF files are accepted.",
  422: "Some fields were rejected by the server.",
};

async function readError(status, text) {
  let detail = "";
  try {
    const data = JSON.parse(text);
    if (typeof data.detail === "string") detail = data.detail;
    else if (Array.isArray(data.detail)) detail = data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  } catch {
    detail = "";
  }
  return detail || DEFAULT_ERRORS[status] || `Request failed (${status}).`;
}

function authHeaders(extra = {}) {
  return state.apiKey ? { ...extra, "x-api-key": state.apiKey } : { ...extra };
}

async function api(path, { method = "GET", json, raw = false, signal } = {}) {
  const headers = authHeaders(json !== undefined ? { "Content-Type": "application/json" } : {});
  let res;
  try {
    res = await fetch(path, { method, headers, body: json !== undefined ? JSON.stringify(json) : undefined, signal });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    setConn("down");
    throw new ApiError(0, DEFAULT_ERRORS[0]);
  }
  if (res.status === 401) setConn("auth");
  if (!res.ok) throw new ApiError(res.status, await readError(res.status, await res.text()));
  return raw ? res : res.json();
}

async function downloadArtifact(url, name) {
  try {
    const res = await api(url, { raw: true });
    const blobUrl = URL.createObjectURL(await res.blob());
    const a = h("a", { href: blobUrl, download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
  } catch (err) {
    // Presigned S3 redirects may be blocked by CORS; open directly when no key is needed.
    if (err.status === 0 && !state.apiKey) window.open(url, "_blank", "noopener");
    else toast(`Download failed: ${err.message}`, "error");
  }
}

/* =========================================================================
   Recent jobs (this device only — IDs and file names, never file contents)
   ========================================================================= */
const RECENT_KEY = "tic.recent";
const recent = {
  all: () => store.get(RECENT_KEY, []),
  get: (id) => recent.all().find((r) => r.id === id),
  upsert(id, patch) {
    const list = recent.all();
    const idx = list.findIndex((r) => r.id === id);
    const next = { ...(idx >= 0 ? list[idx] : { id }), ...patch };
    if (idx >= 0) list.splice(idx, 1);
    list.unshift(next);
    store.set(RECENT_KEY, list.slice(0, 15));
    renderRecent();
    return next;
  },
  touch(id, patch) {
    const list = recent.all();
    const idx = list.findIndex((r) => r.id === id);
    if (idx < 0) return;
    list[idx] = { ...list[idx], ...patch };
    store.set(RECENT_KEY, list);
  },
  remove(id) {
    store.set(RECENT_KEY, recent.all().filter((r) => r.id !== id));
    renderRecent();
  },
};

/* =========================================================================
   Connection + health
   ========================================================================= */
function setConn(next) {
  state.conn = next;
  const dot = $("[data-conn-dot]");
  const label = $("[data-conn-label]");
  dot.dataset.state = next;
  label.textContent = { ok: state.apiKey ? "Connected · key set" : "Connected", auth: "Key required", down: "API offline", unknown: "Connecting…" }[next];
  const status = $("[data-conn-status]");
  if (status) {
    status.textContent = {
      ok: `API reachable at ${location.host}.`,
      auth: "The API is up but rejected the request. Enter the server's API key.",
      down: "The API isn't responding. Start it with `make api`.",
      unknown: "Checking the API…",
    }[next];
  }
}

async function checkHealth() {
  try {
    const res = await fetch("/health", { cache: "no-store" });
    if (!res.ok) throw new Error();
    if (state.conn !== "auth") setConn("ok");
  } catch {
    setConn("down");
  }
}

function initConnection() {
  const dialog = $("[data-conn-dialog]");
  const input = $("[data-api-key]");
  $$("[data-conn-open]").forEach((btn) =>
    btn.addEventListener("click", () => {
      $("[data-menu]").close();
      input.value = state.apiKey;
      dialog.returnValue = "";
      dialog.showModal();
      input.focus();
    }),
  );
  // Enter in the key field means Save (the first submit button is Cancel).
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      dialog.close("save");
    }
  });
  dialog.addEventListener("close", () => {
    if (dialog.returnValue !== "save") return;
    state.apiKey = input.value.trim();
    setConn("unknown");
    checkHealth().then(loadMetrics);
    if (currentRoute.name === "job") jobView.open(currentRoute.id);
    toast(state.apiKey ? "API key set for this tab." : "API key cleared.");
  });
  checkHealth();
  setInterval(checkHealth, 30000);
  window.addEventListener("focus", checkHealth);
}

/* =========================================================================
   Theme
   ========================================================================= */
function initTheme() {
  $("[data-theme-toggle]").addEventListener("click", () => {
    const current = document.documentElement.dataset.theme
      || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = current === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("tic.theme", next);
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event("themechange"));
  });
}

/* =========================================================================
   Router (hash based: #/, #/studio, #/job/<id>, #/help)
   ========================================================================= */
let currentRoute = { name: "home" };
const TITLES = { home: "xCAST — Studio", studio: "New episode · xCAST", help: "Guide · xCAST", notfound: "Not found · xCAST" };

function parseRoute() {
  const hash = location.hash.replace(/^#/, "");
  const legacy = { studio: "/studio", feedback: "/help", docs: "/help", how: "/" };
  if (legacy[hash]) {
    history.replaceState(null, "", `#${legacy[hash]}`);
    return parseRoute();
  }
  const path = hash.startsWith("/") ? hash : `/${hash}`;
  const parts = path.split("/").filter(Boolean);
  if (!parts.length) return { name: "home" };
  if (parts[0] === "studio" && parts.length === 1) return { name: "studio" };
  if (parts[0] === "help" && parts.length === 1) return { name: "help" };
  if (parts[0] === "job" && parts[1]) return { name: "job", id: decodeURIComponent(parts[1]) };
  return { name: "notfound" };
}

function route(first = false) {
  const next = parseRoute();
  if (currentRoute.name === "job" && (next.name !== "job" || next.id !== currentRoute.id)) jobView.close();
  currentRoute = next;
  $$("[data-view]").forEach((v) => (v.hidden = v.dataset.view !== next.name));
  $$("[data-nav]").forEach((a) => {
    const active = a.dataset.nav === next.name || (a.dataset.nav === "studio" && next.name === "job");
    if (active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  $$(".drawer-nav a").forEach((a) => {
    if (a.getAttribute("href") === `#/${next.name === "home" ? "" : next.name}`) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title = next.name === "job" ? `${next.id} · xCAST` : TITLES[next.name] || TITLES.home;
  if (next.name === "studio") {
    renderRecent();
    loadMetrics();
  }
  if (next.name === "job") jobView.open(next.id);
  if (!first) {
    window.scrollTo({ top: 0, behavior: "instant" });
    const heading = $(`[data-view="${next.name}"] h1`);
    if (heading) {
      if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
      heading.focus({ preventScroll: true });
    }
  }
}

/* =========================================================================
   Command palette
   ========================================================================= */
function initPalette() {
  const dialog = $("[data-palette]");
  const input = $("[data-palette-input]");
  const list = $("[data-palette-list]");
  let items = [];
  let active = 0;

  const go = (hash) => () => {
    location.hash = hash;
  };
  const baseCommands = () => {
    const cmds = [
      { group: "Go to", label: "New episode", icon: "upload", hint: "Studio", run: go("#/studio") },
      { group: "Go to", label: "Overview", icon: "home", run: go("#/") },
      { group: "Go to", label: "Guide & troubleshooting", icon: "help", run: go("#/help") },
      { group: "Go to", label: "OpenAPI docs", icon: "braces", hint: "/docs", run: () => window.open("/docs", "_blank", "noopener") },
      { group: "Actions", label: "Toggle light / dark", icon: "sun", run: () => $("[data-theme-toggle]").click() },
      { group: "Actions", label: "Connection & API key", icon: "key", run: () => $("[data-conn-open]").click() },
    ];
    if (currentRoute.name === "job") {
      cmds.push({ group: "Actions", label: "Copy job ID", icon: "copy", hint: currentRoute.id, run: () => copyText(currentRoute.id, "Job ID copied.") });
    }
    recent.all().slice(0, 8).forEach((r) =>
      cmds.push({ group: "Recent jobs", label: r.title || r.file || r.id, icon: "pdf", hint: r.id, run: go(`#/job/${encodeURIComponent(r.id)}`) }),
    );
    return cmds;
  };
  const fuzzy = (q, text) => {
    let i = 0;
    const t = text.toLowerCase();
    for (const ch of q.toLowerCase()) {
      i = t.indexOf(ch, i);
      if (i < 0) return false;
      i += 1;
    }
    return true;
  };
  const render = () => {
    const q = input.value.trim();
    items = baseCommands().filter((c) => !q || fuzzy(q, `${c.label} ${c.hint || ""}`));
    if (q && JOB_ID_RE.test(q)) {
      items.push({ group: "Open", label: `Open job ${q}`, icon: "arrow-right", run: go(`#/job/${encodeURIComponent(q)}`) });
    }
    active = Math.min(active, Math.max(items.length - 1, 0));
    list.replaceChildren();
    if (!items.length) {
      list.append(h("li", { class: "palette-empty", text: "No matches. Paste a full job ID to open it." }));
      return;
    }
    let group = "";
    items.forEach((item, idx) => {
      if (item.group !== group) {
        group = item.group;
        list.append(h("li", { class: "pl-group", role: "presentation", text: group }));
      }
      list.append(
        h("li", {
          role: "option", id: `pl-${idx}`, "aria-selected": String(idx === active),
          onclick: () => runItem(idx), onmousemove: () => setActive(idx),
        }, icon(item.icon), h("span", { text: item.label }), item.hint ? h("small", { text: item.hint }) : null),
      );
    });
    input.setAttribute("aria-activedescendant", `pl-${active}`);
  };
  const setActive = (idx) => {
    if (idx === active) return;
    active = idx;
    $$('[role="option"]', list).forEach((el) => el.setAttribute("aria-selected", String(el.id === `pl-${idx}`)));
    input.setAttribute("aria-activedescendant", `pl-${idx}`);
    $(`#pl-${idx}`, list)?.scrollIntoView({ block: "nearest" });
  };
  const runItem = (idx) => {
    const item = items[idx];
    if (!item) return;
    dialog.close();
    item.run();
  };
  const open = () => {
    if (dialog.open) return;
    input.value = "";
    active = 0;
    render();
    dialog.showModal();
    input.focus();
  };

  input.addEventListener("input", () => {
    active = 0;
    render();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((active + 1) % Math.max(items.length, 1)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive((active - 1 + items.length) % Math.max(items.length, 1)); }
    if (e.key === "Enter") { e.preventDefault(); runItem(active); }
  });
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  $("[data-palette-open]").addEventListener("click", open);
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      open();
    }
  });
}

/* =========================================================================
   Shell: topbar, menu, clipboard, modifier-key labels
   ========================================================================= */
async function copyText(text, message = "Copied.") {
  try {
    await navigator.clipboard.writeText(text);
    toast(message);
  } catch {
    toast("Clipboard unavailable.", "error");
  }
}

function initShell() {
  const topbar = $("[data-topbar]");
  const onScroll = () => topbar.classList.toggle("is-scrolled", window.scrollY > 4);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  const menu = $("[data-menu]");
  $("[data-menu-open]").addEventListener("click", () => menu.showModal());
  menu.addEventListener("click", (e) => {
    if (e.target === menu || e.target.closest("a")) menu.close();
  });

  $$("dialog").forEach((d) => d.addEventListener("click", (e) => {
    if (e.target === d && !d.matches("[data-palette]")) d.close("cancel");
  }));

  $$("[data-mod-key]").forEach((el) => (el.textContent = isMac ? "⌘K" : "Ctrl K"));
  $$("[data-mod-enter]").forEach((el) => (el.textContent = isMac ? "⌘↵" : "Ctrl ↵"));
}

/* =========================================================================
   Overview: interactive demo, code tabs
   ========================================================================= */
function initHome() {
  $$("[data-scroll]").forEach((btn) =>
    btn.addEventListener("click", () => $(btn.dataset.scroll)?.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth" })),
  );

  const demo = $("[data-demo]");
  const tabs = $$("[data-demo-tab]", demo);
  const panes = $$("[data-demo-pane]", demo);
  const wave = $("[data-demo-wave]", demo);
  for (let i = 0; i < 56; i += 1) {
    const hgt = 18 + Math.abs(Math.sin(i * 1.7) * 60 + Math.sin(i * 0.43) * 22);
    const bar = h("i", { class: i < 22 ? "on" : "" });
    bar.style.height = `${Math.min(hgt, 100)}%`;
    bar.style.setProperty("--d", `${(i % 7) * -0.17}s`);
    wave.append(bar);
  }
  let step = 0;
  let timer = null;
  let visible = false;
  const DURATION = 5200;
  demo.style.setProperty("--demo-dur", `${DURATION}ms`);
  const show = (idx) => {
    step = idx;
    tabs.forEach((t, i) => {
      t.setAttribute("aria-selected", String(i === idx));
      t.tabIndex = i === idx ? 0 : -1;
    });
    panes.forEach((p, i) => (p.hidden = i !== idx));
    // restart the progress bar animation
    const bar = $(".demo-progress span", demo);
    bar.style.animation = "none";
    void bar.offsetWidth;
    bar.style.animation = "";
  };
  const stop = () => {
    clearInterval(timer);
    timer = null;
    demo.classList.remove("is-playing");
  };
  const play = () => {
    if (reduceMotion.matches || timer || !visible) return;
    demo.classList.add("is-playing");
    timer = setInterval(() => show((step + 1) % tabs.length), DURATION);
  };
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => {
      stop();
      show(i);
    });
    t.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const next = (i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
      stop();
      show(next);
      tabs[next].focus();
    });
  });
  show(0);
  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    if (visible) play();
    else stop();
  }, { threshold: 0.35 }).observe(demo);

  const card = $("[data-code-tabs]");
  $$("[data-code-tab]", card).forEach((tab) =>
    tab.addEventListener("click", () => {
      $$("[data-code-tab]", card).forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
      $$("pre[data-code]", card).forEach((pre) => (pre.hidden = pre.dataset.code !== tab.dataset.codeTab));
    }),
  );
  $("[data-copy-code]", card).addEventListener("click", () => {
    const pre = $$("pre[data-code]", card).find((p) => !p.hidden);
    copyText(pre.textContent.trim(), "Snippet copied.");
  });
}

/* =========================================================================
   Studio: composer, recent jobs, metrics
   ========================================================================= */
async function inspectPdf(file) {
  const head = new Uint8Array(await file.slice(0, 1024).arrayBuffer());
  const headText = new TextDecoder("latin1").decode(head);
  if (!headText.includes("%PDF-")) return { ok: false };
  let pages = 0;
  if (file.size <= 40 * 1024 * 1024) {
    const text = new TextDecoder("latin1").decode(await file.arrayBuffer());
    pages = (text.match(/\/Type\s*\/Page(?![a-zA-Z])/g) || []).length;
  }
  return { ok: true, pages };
}

function initStudio() {
  const form = $("[data-upload-form]");
  const dz = $("[data-dropzone]");
  const fileInput = $("[data-file-input]");
  const emptyUi = $(".dz-empty", dz);
  const fileUi = $(".dz-file", dz);
  const range = $("[data-duration]");
  const out = $("[data-duration-out]");
  const estimate = $("[data-estimate]");
  const msg = $("[data-form-msg]");
  const submit = $("[data-submit]");
  const submitLabel = $("[data-submit-label]");
  const bar = $("[data-upload-bar]");
  let file = null;
  let fileInfo = { pages: 0 };
  let busy = false;

  const setMsg = (text, tone) => {
    msg.textContent = text || "";
    msg.className = `form-msg${tone ? ` is-${tone}` : ""}`;
  };

  const setFile = async (f) => {
    setMsg("");
    dz.classList.remove("is-invalid");
    if (!f) {
      file = null;
      fileInput.value = "";
      emptyUi.hidden = false;
      fileUi.hidden = true;
      dz.classList.remove("has-file");
      return;
    }
    const looksPdf = f.type === "application/pdf" || f.type === "application/x-pdf" || /\.pdf$/i.test(f.name);
    const info = looksPdf ? await inspectPdf(f).catch(() => ({ ok: true, pages: 0 })) : { ok: false };
    if (!info.ok) {
      dz.classList.add("is-invalid");
      setMsg(`“${f.name}” isn't a PDF.`, "error");
      return;
    }
    file = f;
    fileInfo = info;
    $("[data-file-name]").textContent = f.name;
    $("[data-file-stats]").textContent = [fmtBytes(f.size), info.pages ? `≈ ${info.pages} page${info.pages === 1 ? "" : "s"}` : null]
      .filter(Boolean).join(" · ");
    emptyUi.hidden = true;
    fileUi.hidden = false;
    dz.classList.add("has-file");
  };

  fileInput.addEventListener("change", () => setFile(fileInput.files?.[0] || null));
  $("[data-file-clear]").addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    setFile(null);
    fileInput.focus();
  });
  dz.addEventListener("click", (e) => {
    if (file) e.preventDefault(); // file card is showing; only the clear button acts
  });
  ["dragenter", "dragover"].forEach((type) =>
    dz.addEventListener(type, (e) => {
      e.preventDefault();
      dz.classList.add("is-over");
    }),
  );
  ["dragleave", "dragend"].forEach((type) => dz.addEventListener(type, () => dz.classList.remove("is-over")));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("is-over");
    const f = e.dataTransfer?.files?.[0];
    if (f) setFile(f);
  });
  // Dropping anywhere on the studio view should not navigate away.
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (currentRoute.name === "studio" && e.dataTransfer?.files?.[0] && !dz.contains(e.target)) setFile(e.dataTransfer.files[0]);
  });

  const syncDuration = () => {
    const secs = Number(range.value);
    out.textContent = fmtClock(secs);
    range.style.setProperty("--p", `${((secs - range.min) / (range.max - range.min)) * 100}%`);
    $$("[data-preset]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.preset) === secs)));
    const words = Math.round(secs * WORDS_PER_SECOND);
    estimate.replaceChildren("≈ ", h("b", { text: words.toLocaleString() }), " spoken words · ", h("b", { text: fmtClock(secs) }), " runtime");
  };
  range.addEventListener("input", syncDuration);
  $$("[data-preset]").forEach((b) =>
    b.addEventListener("click", () => {
      range.value = b.dataset.preset;
      syncDuration();
    }),
  );
  syncDuration();

  const doSubmit = () => {
    if (busy) return;
    if (!file) {
      dz.classList.add("is-invalid");
      setMsg("Add a PDF to start.", "error");
      fileInput.focus();
      return;
    }
    const secs = Number(range.value);
    const style = form.querySelector('input[name="style"]:checked')?.value || "everyday";
    const language = $("#language").value;
    const pause = $("[data-pause]").checked;
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("language", language);
    fd.append("style", style);
    fd.append("target_minutes", String(Math.floor(secs / 60)));
    fd.append("target_seconds", String(secs % 60));
    fd.append("pause_at_script", pause ? "true" : "false");

    busy = true;
    submit.disabled = true;
    submitLabel.textContent = "Uploading…";
    bar.hidden = false;
    $("span", bar).style.width = "0%";
    setMsg("");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/v1/jobs");
    Object.entries(authHeaders({ "Idempotency-Key": `studio-${crypto.randomUUID?.() || Date.now().toString(36)}` }))
      .forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.addEventListener("progress", (e) => {
      if (!e.lengthComputable) return;
      const pct = Math.round((e.loaded / e.total) * 100);
      $("span", bar).style.width = `${pct}%`;
      submitLabel.textContent = pct < 100 ? `Uploading ${pct}%` : "Registering job…";
    });
    const done = () => {
      busy = false;
      submit.disabled = false;
      submitLabel.textContent = "Generate episode";
      setTimeout(() => (bar.hidden = true), 400);
    };
    xhr.addEventListener("load", async () => {
      done();
      if (xhr.status === 401) setConn("auth");
      if (xhr.status < 200 || xhr.status >= 300) {
        const message = await readError(xhr.status, xhr.responseText);
        setMsg(message, "error");
        if (xhr.status === 401) $("[data-conn-open]").click();
        return;
      }
      let data = {};
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        setMsg("Unexpected response from the server.", "error");
        return;
      }
      const id = data.job_id;
      recent.upsert(id, {
        file: file.name, size: file.size, pages: fileInfo.pages, language, style, secs, pause,
        status: data.status || "queued", created: new Date().toISOString(),
      });
      toast("Upload received. Job queued.");
      setFile(null);
      location.hash = `#/job/${encodeURIComponent(id)}`;
    });
    xhr.addEventListener("error", () => {
      done();
      setConn("down");
      setMsg(DEFAULT_ERRORS[0], "error");
    });
    xhr.send(fd);
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    doSubmit();
  });
  document.addEventListener("keydown", (e) => {
    if (currentRoute.name === "studio" && (e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      doSubmit();
    }
  });

  $("[data-lookup-form]").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = e.currentTarget.elements.job_id;
    const id = input.value.trim();
    if (!JOB_ID_RE.test(id)) {
      toast("That doesn't look like a job ID.", "error");
      input.focus();
      return;
    }
    input.value = "";
    location.hash = `#/job/${encodeURIComponent(id)}`;
  });

  $("[data-metrics-refresh]").addEventListener("click", loadMetrics);
}

function renderRecent() {
  const listEl = $("[data-recent]");
  if (!listEl) return;
  const items = recent.all();
  listEl.replaceChildren();
  if (!items.length) {
    listEl.append(h("li", {}, h("p", { class: "empty-mini", text: "Jobs you start or open here will be listed for quick access." })));
    return;
  }
  items.slice(0, 8).forEach((r) => {
    listEl.append(
      h("li", {},
        h("a", { href: `#/job/${encodeURIComponent(r.id)}` },
          h("span", { class: "r-icon" }, icon("pdf")),
          h("span", { class: "r-name", text: r.title || r.file || r.id }),
          statusBadge(r.status, true),
          h("span", { class: "r-sub", text: [r.id, r.created ? relTime(r.created) : null].filter(Boolean).join(" · ") }),
        ),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": `Forget ${r.id} on this device`, onclick: () => recent.remove(r.id) }, icon("x")),
      ),
    );
  });
}

async function loadMetrics() {
  const host = $("[data-metrics]");
  if (!host) return;
  try {
    const data = await api("/v1/metrics/summary");
    const counts = data.job_counts || {};
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const avg = (data.stage_metrics && data.stage_metrics.average_seconds) || {};
    const audio = data.audio_metrics || {};
    const order = ["queued", "running", "awaiting_review", "succeeded", "failed"];
    host.replaceChildren(
      h("div", { class: "metric" }, h("b", { text: String(data.queue_depth ?? "—") }), h("small", { text: `Queue depth · ${data.queue_mode || "?"}` })),
      h("div", { class: "metric" }, h("b", { text: audio.total_results ? `${Math.round(audio.audio_success_rate * 100)}%` : "—" }), h("small", { text: "Jobs with audio" })),
      h("div", { class: "metric metric-bar" },
        h("b", { text: String(total) }), h("small", { text: "Jobs on this server" }),
        total
          ? h("div", { class: "stack-bar", role: "img", "aria-label": order.filter((s) => counts[s]).map((s) => `${counts[s]} ${STATUS_LABEL[s]}`).join(", ") },
            ...order.filter((s) => counts[s]).map((s) => {
              const seg = h("i");
              seg.style.width = `${(counts[s] / total) * 100}%`;
              seg.style.background = `var(${STATUS_VAR[s]})`;
              return seg;
            }))
          : null,
        total
          ? h("div", { class: "stack-legend" }, ...order.filter((s) => counts[s]).map((s) => {
            const sw = h("i");
            sw.style.background = `var(${STATUS_VAR[s]})`;
            return h("span", {}, sw, `${STATUS_LABEL[s]} ${counts[s]}`);
          }))
          : null,
      ),
      ...Object.entries(avg).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) =>
        h("div", { class: "metric" }, h("b", { text: `${v < 10 ? v.toFixed(1) : Math.round(v)}s` }), h("small", { text: `avg ${k.replace(/_seconds?$|_s$/, "").replace(/_/g, " ")}` }))),
    );
  } catch (err) {
    host.replaceChildren(
      h("p", { class: "muted small", text: err.status === 401 ? "Add the API key to see server metrics." : err.message }),
      err.status === 401 ? h("button", { class: "btn btn-soft", type: "button", onclick: () => $("[data-conn-open]").click() }, icon("key"), "Add key") : null,
    );
  }
}

/* =========================================================================
   Job workspace
   ========================================================================= */
const ARTIFACT_META = {
  audio_mp3: { label: "Episode audio", icon: "file-audio", c: "--ember" },
  transcript_srt: { label: "Captions (SRT)", icon: "file-caption", c: "--teal" },
  transcript_txt: { label: "Transcript", icon: "file-text", c: "--teal" },
  script_markdown: { label: "Script (Markdown)", icon: "file-text", c: "--violet" },
  script_json: { label: "Script segments", icon: "file-code", c: "--violet" },
  audio_metadata: { label: "Audio metadata", icon: "file-code", c: "--amber" },
  audio_quality: { label: "Audio QA report", icon: "file-chart", c: "--amber" },
  job_metrics: { label: "Stage timings", icon: "file-chart", c: "--amber" },
};
const SPEAKER_CLASSES = ["spk-a", "spk-b", "spk-c", "spk-d"];

const jobView = (() => {
  let j = null; // per-job state
  const els = {};

  const init = () => {
    Object.assign(els, {
      title: $("[data-job-title]"),
      badge: $("[data-job-badge]"),
      badgeLabel: $("[data-job-badge-label]"),
      id: $("[data-job-id]"),
      updated: $("[data-job-updated]"),
      stepper: $("[data-stepper]"),
      notice: $("[data-job-notice]"),
      script: $("[data-script]"),
      listen: $("[data-listen]"),
      files: $("[data-files]"),
      facts: $("[data-facts]"),
      log: $("[data-log]"),
      live: $("[data-live-pill]"),
      countScript: $("[data-count-script]"),
      countFiles: $("[data-count-files]"),
    });
    $("[data-copy-id]").addEventListener("click", () => j && copyText(j.id, "Job ID copied."));
    const tabs = $$("[data-job-tabs] [role=tab]");
    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => selectTab(tab.dataset.tab));
      tab.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        selectTab(next.dataset.tab);
        next.focus();
      });
    });
    $("[data-reject-dialog]").addEventListener("close", onRejectClose);
    document.addEventListener("visibilitychange", () => {
      if (j && !document.hidden && j.pollWaiting) poll();
    });
    window.addEventListener("beforeunload", (e) => {
      if (j && j.mode === "edit" && j.edits.some((s, i) => isDirty(i))) {
        e.preventDefault();
        e.returnValue = "";
      }
    });
    document.addEventListener("keydown", onPlayerKey);
    window.addEventListener("themechange", () => j?.player?.draw());
  };

  const selectTab = (name) => {
    $$("[data-job-tabs] [role=tab]").forEach((t) => {
      const on = t.dataset.tab === name;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
    });
    $$("[data-pane]").forEach((p) => (p.hidden = p.dataset.pane !== name));
    if (j) j.tab = name;
    if (name === "listen") j?.player?.draw();
  };

  /* ---------- lifecycle ---------- */
  const open = (id) => {
    close();
    j = {
      id, status: null, stage: null, last: "", seen: new Set(), tab: "script", mode: null,
      segments: [], edits: [], speakerMap: new Map(), artifacts: null, player: null,
      es: null, pollTimer: null, pollDelay: 1500, pollWaiting: false, abort: new AbortController(),
    };
    const rec = recent.get(id);
    els.title.textContent = rec?.title || (rec?.file ? rec.file.replace(/\.pdf$/i, "") : "Episode");
    els.id.textContent = id;
    els.updated.textContent = "";
    els.log.replaceChildren();
    els.live.hidden = true;
    els.notice.hidden = true;
    els.countScript.textContent = "";
    els.countFiles.textContent = "";
    setBadge(null);
    renderFacts();
    selectTab("script");
    els.script.replaceChildren(h("div", { class: "skeleton" }), h("div", { class: "skeleton" }));
    renderListenEmpty("Checking for audio…");
    els.files.replaceChildren();
    els.stepper.replaceChildren();

    if (!JOB_ID_RE.test(id)) {
      showNotice("error", "Invalid job ID", "Job IDs use letters, numbers, dashes and underscores (3–80 characters).");
      els.script.replaceChildren();
      return;
    }
    fetchStatus(true);
  };

  const close = () => {
    if (!j) return;
    stopStream();
    j.abort.abort();
    j.player?.destroy();
    j = null;
  };

  const fetchStatus = async (initial = false) => {
    const current = j;
    try {
      const data = await api(`/v1/jobs/${encodeURIComponent(current.id)}/status`, { signal: current.abort.signal });
      if (current !== j) return;
      if (!recent.get(current.id)) recent.upsert(current.id, { status: data.status });
      applyStatus(data);
      if (!TERMINAL.has(data.status)) startStream();
    } catch (err) {
      if (err.name === "AbortError" || current !== j) return;
      if (err.status === 404) {
        showNotice("error", "Job not found", "No job with this ID exists on this server. It may have been purged.", {
          label: "Back to studio", run: () => (location.hash = "#/studio"),
        });
        els.script.replaceChildren();
        renderListenEmpty("Nothing to play.");
        setBadge("failed", "Not found");
      } else if (err.status === 401) {
        showNotice("warn", "API key required", "This server protects job data with an API key.", {
          label: "Add key", run: () => $("[data-conn-open]").click(),
        });
        els.script.replaceChildren();
      } else {
        showNotice("error", "Can't load this job", err.message, { label: "Retry", run: () => fetchStatus(initial) });
      }
    }
  };

  /* ---------- live updates ---------- */
  const startStream = () => {
    stopStream();
    if (!j || TERMINAL.has(j.status)) return;
    els.live.hidden = false;
    // EventSource can't send headers, so use it only when no API key is in play.
    if (!state.apiKey && "EventSource" in window) {
      const current = j;
      const es = new EventSource(`/v1/jobs/${encodeURIComponent(current.id)}/progress`);
      current.es = es;
      es.onmessage = (e) => {
        if (current !== j) return es.close();
        try {
          const payload = JSON.parse(e.data);
          applyStatus(payload);
          if (TERMINAL.has(payload.status)) stopStream();
        } catch {
          /* ignore malformed event */
        }
      };
      es.addEventListener("error", () => {
        es.close();
        if (current !== j) return;
        current.es = null;
        if (!TERMINAL.has(current.status)) schedulePoll(2000); // fall back to polling
      });
      return;
    }
    schedulePoll(0);
  };

  const stopStream = () => {
    if (!j) return;
    j.es?.close();
    j.es = null;
    clearTimeout(j.pollTimer);
    j.pollTimer = null;
    j.pollWaiting = false;
    els.live.hidden = true;
  };

  const schedulePoll = (delay) => {
    if (!j) return;
    clearTimeout(j.pollTimer);
    els.live.hidden = false;
    j.pollTimer = setTimeout(poll, delay);
  };

  const poll = async () => {
    const current = j;
    if (!current) return;
    if (document.hidden) {
      current.pollWaiting = true; // resume on visibilitychange
      return;
    }
    current.pollWaiting = false;
    try {
      const data = await api(`/v1/jobs/${encodeURIComponent(current.id)}/status`, { signal: current.abort.signal });
      if (current !== j) return;
      current.pollDelay = 1500;
      applyStatus(data);
      if (!TERMINAL.has(data.status)) schedulePoll(current.pollDelay);
      else stopStream();
    } catch (err) {
      if (err.name === "AbortError" || current !== j) return;
      if (err.status === 401 || err.status === 404) {
        stopStream();
        return fetchStatus();
      }
      current.pollDelay = Math.min(current.pollDelay * 2, 15000);
      schedulePoll(current.pollDelay);
    }
  };

  /* ---------- status → UI ---------- */
  const applyStatus = (p) => {
    const key = JSON.stringify([p.status, p.stage, p.detail, p.error, p.updated_at]);
    if (key === j.last) return;
    j.last = key;
    const prev = j.status;
    j.status = p.status;
    j.stage = p.stage;
    if (p.stage) j.seen.add(p.stage);
    if (p.status === "awaiting_review") j.seen.add("awaiting_review");
    if (p.stage === "reviewed") recent.touch(j.id, { reviewed: true });
    recent.touch(j.id, { status: p.status });

    setBadge(p.status);
    els.updated.textContent = p.updated_at ? `updated ${fmtTimeOfDay(p.updated_at)}` : "";
    appendLog(p);
    renderStepper(p);
    renderNotice(p);
    renderFacts();

    if (p.status === "awaiting_review" && j.mode !== "edit") loadScript("edit");
    else if (p.status === "succeeded" && prev !== "succeeded") {
      loadScript("read");
      loadArtifacts();
      loadTitle();
    } else if (p.status === "failed" && j.mode !== "read") loadScript("read", { quiet: true });
    else if (!j.mode) renderScriptPending();

    if (p.status !== "succeeded" && !j.artifacts) {
      renderListenEmpty(p.status === "failed" ? "This job ended before audio was produced." : "Audio is generated after the script is written" + (reviewFlow() ? " and approved." : "."));
      els.files.replaceChildren(h("li", { class: "empty-state" }, icon("layers", "empty-icon"), h("p", { text: "Files appear here as soon as the job completes." })));
    }
  };

  const setBadge = (status, label) => {
    els.badge.dataset.status = status || "idle";
    els.badgeLabel.textContent = label || STATUS_LABEL[status] || (status ? status : "Loading");
  };

  const appendLog = (p) => {
    const c = STATUS_VAR[p.status] || "--text-3";
    const stageName = { start: "processing", done: "completed", awaiting_review: "awaiting review" }[p.stage] || p.stage || p.status;
    const li = h("li", {},
      h("time", { text: fmtTimeOfDay(p.updated_at) }),
      h("span", { class: "lg-stage", text: stageName }),
      p.error ? h("span", { class: "lg-detail is-error", text: p.error }) : p.detail ? h("span", { class: "lg-detail", text: p.detail }) : null,
    );
    $(".lg-stage", li).style.setProperty("--c", `var(${c})`);
    els.log.prepend(li);
  };

  const reviewFlow = () => {
    const rec = recent.get(j.id);
    return Boolean(rec?.pause || j.seen.has("awaiting_review") || j.seen.has("reviewed") || j.seen.has("rejected"));
  };
  const afterReview = () => j.seen.has("reviewed") || Boolean(recent.get(j.id)?.reviewed);

  const renderStepper = (p) => {
    const review = reviewFlow();
    const steps = review
      ? [
        { label: "Queued", icon: "queue", sub: "Waiting for a worker" },
        { label: "Drafting", icon: "script", sub: "Extract · chunk · write" },
        { label: "Review", icon: "review", sub: "Your approval" },
        { label: "Voicing", icon: "voice", sub: "TTS · mix · captions" },
        { label: "Complete", icon: "check", sub: "Files ready" },
      ]
      : [
        { label: "Queued", icon: "queue", sub: "Waiting for a worker" },
        { label: "Processing", icon: "server", sub: "Extract · script · voice · mix" },
        { label: "Complete", icon: "check", sub: "Files ready" },
      ];
    const synthIdx = review ? 3 : 1;
    const draftIdx = 1;
    let idx = 0;
    let kind = "active";
    switch (p.status) {
      case "queued": idx = review && afterReview() ? synthIdx : 0; break;
      case "running": idx = review && afterReview() ? synthIdx : draftIdx; kind = "running"; break;
      case "awaiting_review": idx = 2; kind = "review"; break;
      case "succeeded": idx = steps.length; break;
      case "failed": idx = p.stage === "rejected" ? 2 : review && afterReview() ? synthIdx : draftIdx; kind = "error"; break;
      default: idx = 0;
    }
    if (p.status === "queued" && idx === synthIdx && review) steps[synthIdx].sub = "Queued for synthesis";
    if (idx < steps.length && p.detail && (p.status === "running" || p.status === "failed")) steps[idx].sub = p.detail;
    if (p.status === "failed" && p.stage === "rejected") steps[2].sub = "Rejected";
    els.stepper.replaceChildren(
      ...steps.map((s, i) => {
        const cls = i < idx ? "is-done" : i === idx ? `is-active${kind === "running" ? " is-running" : kind === "review" ? " is-review" : kind === "error" ? " is-error" : ""}` : "";
        return h("li", { class: cls, "aria-current": i === idx ? "step" : null },
          h("span", { class: "st-node" }, icon(i < idx ? "check" : kind === "error" && i === idx ? "x" : s.icon)),
          h("b", { text: s.label }),
          h("small", { text: s.sub }));
      }),
    );
  };

  const showNotice = (tone, title, body, action) => {
    els.notice.hidden = false;
    els.notice.className = `notice is-${tone}`;
    const iconName = { error: "alert", review: "review", warn: "info", ok: "check" }[tone] || "info";
    els.notice.replaceChildren(
      icon(iconName),
      h("div", {}, h("b", { text: title }), body ? h("span", { class: "muted", text: body }) : null),
      action ? h("button", { class: `btn ${tone === "review" ? "btn-primary" : "btn-soft"}`, type: "button", onclick: action.run }, action.label) : null,
    );
  };

  const renderNotice = (p) => {
    if (p.status === "awaiting_review") {
      showNotice("review", "Your script is ready for review", "Edit any line, then approve to generate audio — or reject it.", {
        label: "Review script", run: () => { selectTab("script"); $(".seg-edit input", els.script)?.focus(); },
      });
    } else if (p.status === "failed") {
      const rejected = p.stage === "rejected";
      showNotice("error", rejected ? "Script rejected" : "This job failed", p.error || p.detail || "Check the worker logs for details.",
        rejected ? null : { label: "New episode", run: () => (location.hash = "#/studio") });
    } else if (p.status === "queued" && !afterReview()) {
      showNotice("warn", "Waiting for a worker", "If this stays queued, make sure a worker is running (make worker).");
    } else if (p.status === "succeeded") {
      showNotice("ok", "Episode ready", "Listen in the browser or download the files.", { label: "Listen", run: () => selectTab("listen") });
    } else {
      els.notice.hidden = true;
    }
  };

  const renderFacts = () => {
    const rec = recent.get(j.id) || {};
    const rows = [
      ["pdf", "Source", rec.file],
      ["doc", "Size", rec.size != null ? `${fmtBytes(rec.size)}${rec.pages ? ` · ≈${rec.pages} pp` : ""}` : null],
      ["globe", "Language", rec.language],
      ["spark", "Tone", rec.style ? STYLE_LABEL[rec.style] || rec.style : null],
      ["clock", "Target", rec.secs ? fmtClock(rec.secs) : null],
      ["review", "Review", rec.pause != null ? (rec.pause ? "Pause at script" : "Straight through") : null],
      ["queue", "Submitted", rec.created ? relTime(rec.created) : null],
    ].filter((r) => r[2]);
    els.facts.replaceChildren();
    if (!rows.length) {
      els.facts.append(h("dt", {}, icon("info"), "Opened by ID"), h("dd", { class: "muted", text: "Submission details are kept only on the device that uploaded it." }));
      return;
    }
    rows.forEach(([ic, k, v]) => els.facts.append(h("dt", {}, icon(ic), k), h("dd", { text: v })));
  };

  const loadTitle = async () => {
    const current = j;
    try {
      const result = await api(`/v1/jobs/${encodeURIComponent(current.id)}/result`, { signal: current.abort.signal });
      if (current !== j || !result.title) return;
      els.title.textContent = result.title;
      recent.touch(current.id, { title: result.title });
    } catch {
      /* title is optional */
    }
  };

  /* ---------- script ---------- */
  const renderScriptPending = () => {
    els.script.replaceChildren(
      h("div", { class: "empty-state" }, icon("script", "empty-icon"), h("h3", { text: "The script is being written" }),
        h("p", { text: "Segments, speakers and citations will appear here as soon as the worker drafts them." })),
    );
  };

  const loadScript = async (mode, { quiet = false } = {}) => {
    const current = j;
    current.mode = mode;
    if (!quiet) els.script.replaceChildren(h("div", { class: "skeleton" }), h("div", { class: "skeleton" }));
    try {
      const data = await api(`/v1/jobs/${encodeURIComponent(current.id)}/script`, { signal: current.abort.signal });
      if (current !== j) return;
      current.segments = Array.isArray(data.segments) ? data.segments : [];
      current.edits = current.segments.map((s) => ({ ...s }));
      current.speakerMap = new Map();
      current.segments.forEach((s) => speakerClass(s.speaker));
      renderScript();
    } catch (err) {
      if (err.name === "AbortError" || current !== j) return;
      if (quiet) {
        els.script.replaceChildren(h("div", { class: "empty-state" }, icon("script", "empty-icon"), h("p", { text: "No script was produced for this job." })));
        return;
      }
      els.script.replaceChildren(
        h("div", { class: "empty-state" }, icon("alert", "empty-icon"), h("h3", { text: "Couldn't load the script" }), h("p", { text: err.message }),
          h("button", { class: "btn btn-soft", type: "button", onclick: () => loadScript(mode) }, icon("refresh"), "Retry")),
      );
    }
  };

  const speakerClass = (name) => {
    const key = (name || "Host").trim().toLowerCase();
    if (!j.speakerMap.has(key)) j.speakerMap.set(key, SPEAKER_CLASSES[j.speakerMap.size % SPEAKER_CLASSES.length]);
    return j.speakerMap.get(key);
  };

  const isDirty = (i) => {
    const a = j.segments[i];
    const b = j.edits[i];
    return a.title !== b.title || a.speaker !== b.speaker || a.text !== b.text;
  };

  const citeChips = (seg, container) => {
    const cites = Array.isArray(seg.citations) ? seg.citations : [];
    if (!cites.length) return [h("span", { class: "no-cite" }, icon("alert"), "No citation")];
    return cites.map((c) => {
      const label = c.page != null ? `p.${c.page}` : (c.source || "source").slice(0, 18);
      const chip = h("button", { class: "cite-chip", type: "button", "aria-expanded": "false", title: c.source || "" }, icon("cite"), label);
      chip.addEventListener("click", () => {
        const open = chip.getAttribute("aria-expanded") === "true";
        $$(".cite-chip", container).forEach((x) => x.setAttribute("aria-expanded", "false"));
        $(".seg-snippet", container)?.remove();
        if (open) return;
        chip.setAttribute("aria-expanded", "true");
        container.append(
          h("blockquote", { class: "seg-snippet" }, c.snippet || "No snippet recorded for this citation.",
            h("cite", { text: [c.source, c.page != null ? `page ${c.page}` : null].filter(Boolean).join(" · ") })),
        );
      });
      return chip;
    });
  };

  const renderScript = () => {
    const segs = j.mode === "edit" ? j.edits : j.segments;
    els.countScript.textContent = segs.length ? String(segs.length) : "";
    if (!segs.length) {
      els.script.replaceChildren(h("div", { class: "empty-state" }, icon("script", "empty-icon"), h("p", { text: "The script has no segments." })));
      return;
    }
    const totalWords = segs.reduce((n, s) => n + wordCount(s.text), 0);
    const speakers = [...new Set(segs.map((s) => (s.speaker || "Host").trim()))];
    const cited = segs.filter((s) => s.citations && s.citations.length).length;
    const toolbar = h("div", { class: "script-toolbar" },
      h("div", { class: "speaker-legend" }, ...speakers.map((name) =>
        h("span", { class: speakerClass(name) }, h("span", { class: "avatar", text: name.slice(0, 1).toUpperCase() }), name))),
      h("span", { class: "script-stats", "data-script-stats": "" }, `${totalWords.toLocaleString()} words · ≈${fmtClock(totalWords / WORDS_PER_SECOND)} · ${cited}/${segs.length} cited`),
    );
    const list = h("ol", { class: "segments" });
    segs.forEach((seg, i) => list.append(j.mode === "edit" ? editSegment(seg, i) : readSegment(seg)));
    const nodes = [toolbar, list];
    if (j.mode === "edit") nodes.push(reviewBar());
    els.script.replaceChildren(...nodes);
    if (j.mode === "edit") updateReviewInfo();
  };

  const readSegment = (seg) => {
    const body = h("div", {},
      h("div", { class: "seg-head" }, h("span", { class: "seg-num" }), h("h3", { class: "seg-title", text: seg.title || "Untitled" }), h("span", { class: "seg-speaker", text: seg.speaker || "Host" })),
      h("p", { class: "seg-text", text: seg.text || "" }),
    );
    const meta = h("div", { class: "seg-meta" });
    meta.append(...citeChips(seg, body), h("span", { class: "seg-est", text: `≈${fmtClock(wordCount(seg.text) / WORDS_PER_SECOND)}` }));
    body.append(meta);
    return h("li", { class: `segment ${speakerClass(seg.speaker)}` }, h("span", { class: "avatar", text: (seg.speaker || "H").slice(0, 1).toUpperCase() }), body);
  };

  const editSegment = (seg, i) => {
    const li = h("li", { class: `segment ${speakerClass(seg.speaker)}` });
    const avatar = h("span", { class: "avatar", text: (seg.speaker || "H").slice(0, 1).toUpperCase() });
    const dirty = h("span", { class: "seg-dirty", text: "Edited", hidden: true });
    const est = h("span", { class: "seg-est" });
    const speaker = h("input", { class: "input", value: seg.speaker || "", "aria-label": `Segment ${i + 1} speaker`, maxLength: 60 });
    const title = h("input", { class: "input seg-title-input", value: seg.title || "", "aria-label": `Segment ${i + 1} title` });
    const text = h("textarea", { class: "input", rows: 4, "aria-label": `Segment ${i + 1} narration` });
    text.value = seg.text || "";
    const reset = h("button", { class: "icon-btn sm", type: "button", "aria-label": `Undo edits to segment ${i + 1}`, hidden: true }, icon("undo"));
    const body = h("div", {},
      h("div", { class: "seg-head" }, h("span", { class: "seg-num" }), dirty),
      h("div", { class: "seg-edit" }, h("div", { class: "seg-edit-row" }, speaker, title), text),
    );
    const meta = h("div", { class: "seg-meta" }, ...citeChips(seg, body), reset, est);
    body.append(meta);
    li.append(avatar, body);

    const sync = () => {
      const e = j.edits[i];
      e.speaker = speaker.value;
      e.title = title.value;
      e.text = text.value;
      const d = isDirty(i);
      li.classList.toggle("is-dirty", d);
      dirty.hidden = !d;
      reset.hidden = !d;
      const cls = speakerClass(e.speaker);
      SPEAKER_CLASSES.forEach((c) => li.classList.toggle(c, c === cls));
      avatar.textContent = (e.speaker || "H").slice(0, 1).toUpperCase();
      const words = wordCount(e.text);
      est.textContent = `${words} words · ≈${fmtClock(words / WORDS_PER_SECOND)}`;
      autosize(text);
      updateReviewInfo();
    };
    [speaker, title, text].forEach((el) => el.addEventListener("input", sync));
    reset.addEventListener("click", () => {
      const o = j.segments[i];
      speaker.value = o.speaker || "";
      title.value = o.title || "";
      text.value = o.text || "";
      sync();
      text.focus();
    });
    requestAnimationFrame(() => autosize(text));
    sync();
    return li;
  };

  const autosize = (ta) => {
    if (CSS.supports?.("field-sizing", "content")) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight + 2}px`;
  };

  const reviewBar = () =>
    h("div", { class: "review-bar", role: "region", "aria-label": "Review actions" },
      h("span", { class: "rb-info" }, icon("review"), h("span", { "data-rb-info": "" })),
      h("div", { class: "rb-actions" },
        h("button", { class: "btn btn-danger-ghost", type: "button", onclick: () => {
          const d = $("[data-reject-dialog]");
          d.returnValue = "";
          d.showModal();
        } }, icon("x"), "Reject"),
        h("button", { class: "btn btn-primary", type: "button", "data-approve": "", onclick: approve }, icon("voice"), "Approve & voice"),
      ),
    );

  const updateReviewInfo = () => {
    const info = $("[data-rb-info]", els.script);
    if (!info) return;
    const edited = j.edits.filter((_, i) => isDirty(i)).length;
    const words = j.edits.reduce((n, s) => n + wordCount(s.text), 0);
    info.textContent = `${j.edits.length} segments · ${edited ? `${edited} edited` : "no edits"} · ≈${fmtClock(words / WORDS_PER_SECOND)}`;
    const stats = $("[data-script-stats]", els.script);
    const cited = j.edits.filter((s) => s.citations && s.citations.length).length;
    if (stats) stats.textContent = `${words.toLocaleString()} words · ≈${fmtClock(words / WORDS_PER_SECOND)} · ${cited}/${j.edits.length} cited`;
  };

  const approve = async (e) => {
    const btn = e.currentTarget;
    const emptyIdx = j.edits.findIndex((s) => !s.text.trim());
    if (emptyIdx >= 0) {
      toast(`Segment ${emptyIdx + 1} has no narration.`, "error");
      $$(".segment textarea", els.script)[emptyIdx]?.focus();
      return;
    }
    btn.disabled = true;
    const current = j;
    try {
      await api(`/v1/jobs/${encodeURIComponent(current.id)}/review`, {
        method: "POST",
        json: { action: "approve", segments: current.edits.map((s) => ({ ...s, speaker: s.speaker.trim() || "Host", title: s.title.trim() || "Untitled" })) },
      });
      if (current !== j) return;
      recent.touch(current.id, { reviewed: true });
      current.seen.add("reviewed");
      current.segments = current.edits.map((s) => ({ ...s }));
      current.mode = "read";
      renderScript();
      toast("Script approved. Audio synthesis queued.");
      fetchStatus();
    } catch (err) {
      btn.disabled = false;
      toast(`Approve failed: ${err.message}`, "error");
    }
  };

  const onRejectClose = async () => {
    const dialog = $("[data-reject-dialog]");
    if (dialog.returnValue !== "reject" || !j) return;
    const note = $("[data-reject-note]").value.trim();
    const current = j;
    try {
      await api(`/v1/jobs/${encodeURIComponent(current.id)}/review`, {
        method: "POST", json: { action: "reject", notes: note || "Rejected by reviewer in Studio" },
      });
      if (current !== j) return;
      $("[data-reject-note]").value = "";
      current.mode = "read";
      renderScript();
      toast("Script rejected.");
      fetchStatus();
    } catch (err) {
      toast(`Reject failed: ${err.message}`, "error");
    }
  };

  /* ---------- artifacts ---------- */
  const loadArtifacts = async () => {
    const current = j;
    els.files.replaceChildren(h("li", { class: "skeleton" }));
    try {
      const data = await api(`/v1/jobs/${encodeURIComponent(current.id)}/artifacts`, { signal: current.abort.signal });
      if (current !== j) return;
      current.artifacts = data.artifacts || [];
      renderFiles();
      setupPlayer();
    } catch (err) {
      if (err.name === "AbortError" || current !== j) return;
      current.artifacts = [];
      els.files.replaceChildren(h("li", { class: "empty-state" }, icon("alert", "empty-icon"), h("p", { text: `Files unavailable: ${err.message}` })));
      renderListenEmpty("Audio unavailable.");
    }
  };

  const renderFiles = () => {
    const list = j.artifacts;
    els.countFiles.textContent = list.length ? String(list.length) : "";
    if (!list.length) {
      els.files.replaceChildren(h("li", { class: "empty-state" }, icon("layers", "empty-icon"), h("p", { text: "This job didn't produce any downloadable files." })));
      return;
    }
    const order = Object.keys(ARTIFACT_META);
    const sorted = [...list].sort((a, b) => (order.indexOf(a.kind) + 1 || 99) - (order.indexOf(b.kind) + 1 || 99));
    els.files.replaceChildren(...sorted.map((a) => {
      const meta = ARTIFACT_META[a.kind] || { label: a.kind || "File", icon: "doc", c: "--text-3" };
      const ic = h("span", { class: "fc-icon" }, icon(meta.icon));
      const card = h("li", { class: "file-card" },
        ic, h("b", { text: a.name, title: a.name }), h("small", { text: `${meta.label} · ${fmtBytes(a.size_bytes)}` }),
        h("button", { class: "btn btn-soft", type: "button", onclick: () => downloadArtifact(a.download_url, a.name) }, icon("download"), "Download"));
      card.style.setProperty("--c", `var(${meta.c})`);
      return card;
    }));
  };

  /* ---------- player ---------- */
  const renderListenEmpty = (text) => {
    els.listen.replaceChildren(h("div", { class: "empty-state" }, icon("wave", "empty-icon"), h("p", { text })));
  };

  const setupPlayer = async () => {
    const current = j;
    const mp3 = current.artifacts.find((a) => a.kind === "audio_mp3" || /\.mp3$/i.test(a.name));
    if (!mp3) {
      renderListenEmpty("This job produced no audio. TTS may be disabled on the worker — the script and transcript are in Files.");
      return;
    }
    renderListenEmpty("Loading audio…");
    try {
      const res = await api(mp3.download_url, { raw: true, signal: current.abort.signal });
      const buf = await res.arrayBuffer();
      if (current !== j) return;
      let cues = [];
      const srt = current.artifacts.find((a) => a.kind === "transcript_srt");
      if (srt) {
        try {
          const text = await (await api(srt.download_url, { raw: true, signal: current.abort.signal })).text();
          cues = parseSrt(text);
        } catch {
          cues = [];
        }
      }
      if (current !== j) return;
      current.player = createPlayer(buf, cues, els.title.textContent);
    } catch (err) {
      if (err.name === "AbortError" || current !== j) return;
      renderListenEmpty(`Couldn't load audio: ${err.message}`);
    }
  };

  const parseSrt = (text) =>
    text.replace(/\r/g, "").split(/\n{2,}/).map((block) => {
      const lines = block.trim().split("\n");
      const tIdx = lines.findIndex((l) => l.includes("-->"));
      if (tIdx < 0) return null;
      const [a, b] = lines[tIdx].split("-->").map((s) => s.trim());
      const toSec = (ts) => {
        const m = ts.match(/(\d+):(\d+):(\d+)[,.](\d+)/);
        return m ? +m[1] * 3600 + +m[2] * 60 + +m[3] + +m[4] / 1000 : 0;
      };
      const body = lines.slice(tIdx + 1).join(" ");
      const m = body.match(/^([^:]{1,40}):\s*(.*)$/);
      return { start: toSec(a), end: toSec(b), speaker: m ? m[1] : "", text: m ? m[2] : body };
    }).filter(Boolean);

  function createPlayer(arrayBuffer, cues, title) {
    const blobUrl = URL.createObjectURL(new Blob([arrayBuffer], { type: "audio/mpeg" }));
    const audio = new Audio(blobUrl);
    audio.preload = "metadata";
    const speeds = [1, 1.25, 1.5, 1.75, 2, 0.75];
    let speedIdx = 0;
    let peaks = null;
    let hoverX = null;

    const playBtn = h("button", { class: "play-btn", type: "button", "aria-label": "Play" }, icon("play", "icon icon-play"));
    const speedBtn = h("button", { class: "speed-btn", type: "button", "aria-label": "Playback speed", text: "1×" });
    const back = h("button", { class: "icon-btn", type: "button", "aria-label": "Back 15 seconds" }, icon("back"));
    const fwd = h("button", { class: "icon-btn", type: "button", "aria-label": "Forward 15 seconds" }, icon("fwd"));
    const dl = h("button", { class: "icon-btn", type: "button", "aria-label": "Download audio" }, icon("download"));
    const canvas = h("canvas");
    const hover = h("span", { class: "wave-hover" }, h("span", { class: "wave-tip" }));
    const marks = h("div", { class: "wave-marks", "aria-hidden": "true" });
    const wave = h("div", {
      class: "wave-wrap", role: "slider", tabindex: "0", "aria-label": "Seek", "aria-valuemin": "0", "aria-valuemax": "0", "aria-valuenow": "0",
    }, canvas, hover, marks);
    const cur = h("b", { text: "0:00" });
    const dur = h("span", { text: "--:--" });
    const capsList = h("div", { class: "captions", role: "list", "aria-label": "Transcript" });

    const root = h("div", {},
      h("div", { class: "player" },
        h("div", { class: "player-top" },
          playBtn,
          h("div", { class: "player-title" }, h("b", { text: title }), h("small", { text: "episode.mp3 · Space to play, ← → to seek" })),
          h("div", { class: "player-ctrls" }, back, fwd, speedBtn, dl)),
        wave,
        h("div", { class: "times" }, cur, dur)),
    );
    if (cues.length) {
      cues.forEach((cue, i) => {
        const btn = h("button", { class: `cap ${speakerClass(cue.speaker)}`, type: "button", role: "listitem", dataset: { i: String(i) } },
          h("time", { text: fmtClock(cue.start) }), h("span", {}, cue.speaker ? h("b", { text: cue.speaker }) : null, cue.text));
        btn.addEventListener("click", () => {
          audio.currentTime = cue.start;
          if (audio.paused) audio.play();
        });
        capsList.append(btn);
      });
      root.append(capsList, h("p", { class: "cap-note" }, icon("info"), "Caption timings are estimated from word counts and may drift from the audio."));
    }
    els.listen.replaceChildren(root);

    const setPlayIcon = () => {
      playBtn.replaceChildren(icon(audio.paused ? "play" : "pause", `icon${audio.paused ? " icon-play" : ""}`));
      playBtn.setAttribute("aria-label", audio.paused ? "Play" : "Pause");
    };
    const toggle = () => (audio.paused ? audio.play() : audio.pause());
    const seekBy = (d) => {
      audio.currentTime = Math.max(0, Math.min((audio.duration || 0), audio.currentTime + d));
    };

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
      const ctx = canvas.getContext("2d");
      ctx.scale(dpr, dpr);
      const W = rect.width;
      const H = rect.height;
      const barW = 3;
      const gap = 2;
      const n = Math.floor(W / (barW + gap));
      const progress = audio.duration ? audio.currentTime / audio.duration : 0;
      const grad = ctx.createLinearGradient(0, 0, W, 0);
      grad.addColorStop(0, cssVar("--ember") || "#ff7a3d");
      grad.addColorStop(0.55, cssVar("--rose") || "#f0457a");
      grad.addColorStop(1, cssVar("--violet") || "#8b73ff");
      const idle = cssVar("--line-2") || "rgba(255,255,255,.14)";
      const hoverFill = cssVar("--text-3") || "#777";
      ctx.clearRect(0, 0, W, H);
      for (let i = 0; i < n; i += 1) {
        const pos = i / n;
        let amp;
        if (peaks) {
          const from = Math.floor(pos * peaks.length);
          const to = Math.max(from + 1, Math.floor(((i + 1) / n) * peaks.length));
          amp = 0;
          for (let k = from; k < to; k += 1) amp = Math.max(amp, peaks[k]);
        } else {
          amp = 0.25 + 0.2 * Math.abs(Math.sin(i * 0.9)); // placeholder until decoded
        }
        const bh = Math.max(3, amp * (H - 6));
        const x = i * (barW + gap);
        ctx.fillStyle = pos < progress ? grad : hoverX != null && x < hoverX ? hoverFill : idle;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x, (H - bh) / 2, barW, bh, 1.5);
        else ctx.rect(x, (H - bh) / 2, barW, bh);
        ctx.fill();
      }
    };

    // Decode for real waveform peaks (best effort).
    (async () => {
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        const ctx = new Ctx();
        const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
        const data = decoded.getChannelData(0);
        const buckets = 1200;
        const size = Math.floor(data.length / buckets) || 1;
        const out = new Float32Array(buckets);
        let max = 0;
        for (let b = 0; b < buckets; b += 1) {
          let sum = 0;
          const start = b * size;
          for (let k = 0; k < size && start + k < data.length; k += 4) sum += data[start + k] ** 2;
          out[b] = Math.sqrt(sum / (size / 4));
          max = Math.max(max, out[b]);
        }
        peaks = out.map((v) => (max ? Math.pow(v / max, 0.8) : 0));
        ctx.close?.();
        draw();
      } catch {
        /* keep placeholder bars */
      }
    })();

    let activeCue = -1;
    const syncCaptions = () => {
      if (!cues.length) return;
      const t = audio.currentTime;
      const idx = cues.findIndex((c) => t >= c.start && t < c.end + 0.5);
      if (idx === activeCue) return;
      capsList.children[activeCue]?.classList.remove("is-on");
      activeCue = idx;
      const el = capsList.children[idx];
      if (el) {
        el.classList.add("is-on");
        const top = el.offsetTop - capsList.clientHeight / 2 + el.clientHeight / 2;
        capsList.scrollTo({ top, behavior: reduceMotion.matches ? "auto" : "smooth" });
      }
    };
    const placeMarks = () => {
      marks.replaceChildren();
      if (!audio.duration || !cues.length) return;
      cues.forEach((c) => {
        const m = h("i");
        m.style.left = `${Math.min(100, (c.start / audio.duration) * 100)}%`;
        marks.append(m);
      });
    };

    let raf = 0;
    const tick = () => {
      cur.textContent = fmtClock(audio.currentTime);
      wave.setAttribute("aria-valuenow", String(Math.round(audio.currentTime)));
      wave.setAttribute("aria-valuetext", `${fmtClock(audio.currentTime)} of ${fmtClock(audio.duration)}`);
      draw();
      syncCaptions();
      if (!audio.paused) raf = requestAnimationFrame(tick);
    };

    audio.addEventListener("loadedmetadata", () => {
      dur.textContent = fmtClock(audio.duration);
      wave.setAttribute("aria-valuemax", String(Math.round(audio.duration)));
      placeMarks();
      draw();
    });
    audio.addEventListener("play", () => { setPlayIcon(); cancelAnimationFrame(raf); raf = requestAnimationFrame(tick); });
    audio.addEventListener("pause", () => { setPlayIcon(); tick(); });
    audio.addEventListener("ended", setPlayIcon);
    audio.addEventListener("seeked", tick);

    playBtn.addEventListener("click", toggle);
    back.addEventListener("click", () => seekBy(-15));
    fwd.addEventListener("click", () => seekBy(15));
    speedBtn.addEventListener("click", () => {
      speedIdx = (speedIdx + 1) % speeds.length;
      audio.playbackRate = speeds[speedIdx];
      speedBtn.textContent = `${speeds[speedIdx]}×`;
    });
    const mp3 = j.artifacts.find((a) => a.kind === "audio_mp3" || /\.mp3$/i.test(a.name));
    dl.addEventListener("click", () => downloadArtifact(mp3.download_url, mp3.name));

    const seekToX = (clientX) => {
      const rect = wave.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      if (audio.duration) audio.currentTime = ratio * audio.duration;
    };
    let dragging = false;
    wave.addEventListener("pointerdown", (e) => { dragging = true; wave.setPointerCapture(e.pointerId); seekToX(e.clientX); });
    wave.addEventListener("pointermove", (e) => {
      const rect = wave.getBoundingClientRect();
      hoverX = e.clientX - rect.left;
      hover.style.left = `${hoverX}px`;
      $(".wave-tip", hover).textContent = fmtClock((hoverX / rect.width) * (audio.duration || 0));
      if (dragging) seekToX(e.clientX);
      else draw();
    });
    wave.addEventListener("pointerup", () => (dragging = false));
    wave.addEventListener("pointerleave", () => { hoverX = null; draw(); });
    wave.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") { e.preventDefault(); e.stopPropagation(); seekBy(5); }
      if (e.key === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); seekBy(-5); }
      if (e.key === "Home") { e.preventDefault(); audio.currentTime = 0; }
      if (e.key === "End") { e.preventDefault(); audio.currentTime = audio.duration || 0; }
    });

    const ro = new ResizeObserver(() => draw());
    ro.observe(wave);

    if ("mediaSession" in navigator) {
      try {
        navigator.mediaSession.metadata = new MediaMetadata({
          title, artist: "xCAST", artwork: [{ src: "/assets/branding/app-icon.png", sizes: "512x512", type: "image/png" }],
        });
        navigator.mediaSession.setActionHandler("seekbackward", () => seekBy(-15));
        navigator.mediaSession.setActionHandler("seekforward", () => seekBy(15));
      } catch {
        /* optional */
      }
    }

    requestAnimationFrame(draw);
    return {
      draw,
      toggle,
      seekBy,
      destroy() {
        audio.pause();
        cancelAnimationFrame(raf);
        ro.disconnect();
        URL.revokeObjectURL(blobUrl);
      },
    };
  }

  function onPlayerKey(e) {
    if (!j?.player || currentRoute.name !== "job" || j.tab !== "listen") return;
    if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("dialog[open]")) return;
    if (e.key.startsWith("Arrow") && e.target.closest?.('[role="tab"], [role="slider"]')) return;
    if (e.key === " " && !(e.target instanceof HTMLButtonElement)) {
      e.preventDefault();
      j.player.toggle();
    } else if (e.key === "ArrowRight" && !e.target.closest?.(".wave-wrap")) {
      j.player.seekBy(5);
    } else if (e.key === "ArrowLeft" && !e.target.closest?.(".wave-wrap")) {
      j.player.seekBy(-5);
    }
  }

  return { init, open, close };
})();

/* =========================================================================
   Guide: section jump + feedback
   ========================================================================= */
function initHelp() {
  const links = $$("[data-jump]");
  links.forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      $(`#${a.dataset.jump}`)?.scrollIntoView({ behavior: reduceMotion.matches ? "auto" : "smooth" });
    }),
  );
  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      links.forEach((a) => a.classList.toggle("is-on", a.dataset.jump === entry.target.id));
    });
  }, { rootMargin: "-30% 0px -60% 0px" });
  links.forEach((a) => {
    const section = document.getElementById(a.dataset.jump);
    if (section) io.observe(section);
  });

  const form = $("[data-feedback-form]");
  const msg = $("[data-feedback-msg]");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const message = String(fd.get("message") || "").trim();
    if (message.length < 4) {
      msg.textContent = "Please write at least a few words.";
      msg.className = "form-msg is-error";
      form.elements.message.focus();
      return;
    }
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    msg.textContent = "Sending…";
    msg.className = "form-msg";
    try {
      await api("/v1/feedback", {
        method: "POST",
        json: {
          message,
          name: String(fd.get("name") || "").trim() || null,
          email: String(fd.get("email") || "").trim() || null,
          job_id: String(fd.get("job_id") || "").trim() || null,
          context: fd.get("context") ? { area: String(fd.get("context")) } : null,
        },
      });
      form.reset();
      msg.textContent = "Thanks — feedback received.";
      msg.className = "form-msg is-ok";
    } catch (err) {
      msg.textContent = err.message;
      msg.className = "form-msg is-error";
    } finally {
      btn.disabled = false;
    }
  });
}

/* =========================================================================
   Boot
   ========================================================================= */
initShell();
initTheme();
initConnection();
initPalette();
initHome();
initStudio();
initHelp();
jobView.init();
window.addEventListener("hashchange", () => route());
route(true);
