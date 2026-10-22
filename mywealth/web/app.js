/* myWealth — UI logic. Vanilla JS, no external dependencies. */
(() => {
  "use strict";

  const TOKEN = document.querySelector('meta[name="mywealth-token"]').content;
  const LOCALE = "it-IT";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];

  const VIEWS = {
    home: "Home",
    operazioni: "Operazioni",
    investimenti: "Investimenti",
    analytics: "Analytics",
    export: "Export",
    impostazioni: "Impostazioni",
  };
  const THEME_NAMES = { system: "Sistema", light: "Chiaro", dark: "Scuro" };

  const state = { settings: { theme: "system" }, status: null };

  // ------------------------------------------------------------ utilities ----
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch (e) { return null; }
  }

  async function api(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: { "X-MyWealth-Token": TOKEN, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch (e) { /* empty response */ }
    if (!res.ok) throw new Error(data.error || `Errore ${res.status}`);
    return data;
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let toastTimer;
  function toast(msg, isError = false) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.toggle("err", isError);
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), isError ? 5000 : 2500);
  }

  // --------------------------------------------------------------- router ----
  function currentView() {
    const v = location.hash.slice(1);
    return v in VIEWS ? v : "home";
  }

  function showView() {
    const view = currentView();
    $$("#nav a").forEach((a) => {
      const on = a.dataset.view === view;
      a.classList.toggle("on", on);
      if (on) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    $$(".view").forEach((s) => { s.hidden = s.dataset.view !== view; });
    $("#page-title").textContent = VIEWS[view];
    document.title = view === "home" ? "myWealth" : `${VIEWS[view]} · myWealth`;
  }

  // ---------------------------------------------------------------- theme ----
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
  const effectiveTheme = (t) => (t === "system" ? (systemDark.matches ? "dark" : "light") : t);

  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    store("mw-theme", theme === "system" ? null : theme);
    $("#theme-label").textContent = `Tema: ${THEME_NAMES[theme] || THEME_NAMES.system}`;
    $$("[data-theme-choice]").forEach((b) => {
      const on = b.dataset.themeChoice === theme;
      b.classList.toggle("on", on);
      b.setAttribute("aria-checked", String(on));
    });
  }

  async function saveTheme(theme) {
    const previous = state.settings.theme;
    applyTheme(theme);
    try {
      state.settings = await api("PUT", "/api/settings", { theme });
    } catch (e) {
      applyTheme(previous);
      toast(e.message, true);
    }
  }

  // ----------------------------------------------------------------- info ----
  function renderInfo() {
    const s = state.status;
    if (!s) return;
    const rows = [
      ["Versione", esc(s.version)],
      ["Modalità", s.demo ? "Demo (database temporaneo)" : "Normale"],
      ["Cartella dati", `<span class="mono">${esc(s.data_dir)}</span>`],
      ["Schema database", `v${esc(s.schema_version)}`],
    ];
    $("#info").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  }

  // ----------------------------------------------------------------- exit ----
  async function exitApp() {
    const btn = $("#btn-exit");
    btn.disabled = true;
    try {
      await api("POST", "/api/shutdown");
      $("#closed").hidden = false;
      document.title = "myWealth · chiuso";
      try { window.close(); } catch (e) { /* only works for windows opened by script */ }
    } catch (e) {
      btn.disabled = false;
      toast(e.message, true);
    }
  }

  // ----------------------------------------------------------------- init ----
  function init() {
    const today = new Date().toLocaleDateString(LOCALE, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    $("#today").textContent = today;

    window.addEventListener("hashchange", showView);
    showView();

    state.settings.theme = store("mw-theme") || "system";
    applyTheme(state.settings.theme);
    $("#btn-theme").addEventListener("click", () => {
      saveTheme(effectiveTheme(state.settings.theme) === "dark" ? "light" : "dark");
    });
    $$("[data-theme-choice]").forEach((b) => b.addEventListener("click", () => saveTheme(b.dataset.themeChoice)));
    $("#btn-exit").addEventListener("click", exitApp);

    Promise.all([api("GET", "/api/settings"), api("GET", "/api/status")])
      .then(([settings, status]) => {
        state.settings = settings;
        state.status = status;
        applyTheme(settings.theme);
        $("#demo-banner").hidden = !status.demo;
        renderInfo();
      })
      .catch((e) => toast(e.message, true));
  }

  init();
})();
