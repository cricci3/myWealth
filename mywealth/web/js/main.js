/* myWealth — UI entry point: router, theme, exit. Vanilla JS modules, no external dependencies. */
import { $, $$, api, changed, onChange, state, store, toast, LOCALE, loadAccounts, loadRates } from "./core.js";
import home from "./views/home.js";
import settingsView from "./views/settings.js";
import operations from "./views/operations.js";
import investments from "./views/investments.js";

const VIEWS = {
  home: { title: "Home", view: home },
  operazioni: { title: "Operazioni", view: operations },
  investimenti: { title: "Investimenti", view: investments },
  analytics: { title: "Analytics", view: placeholder("Analisi", "In arrivo · M7") },
  export: { title: "Export", view: placeholder("Esporta i dati", "In arrivo · M8") },
  impostazioni: { title: "Impostazioni", view: settingsView },
};
const THEME_NAMES = { system: "Sistema", light: "Chiaro", dark: "Scuro" };

function placeholder(title, tag) {
  return {
    mount(el) { el.innerHTML = `<div class="card empty"><h2>${title}</h2><span class="tag">${tag}</span></div>`; },
    show() {},
  };
}

// ------------------------------------------------------------------ router --
const mounted = new Set();
const stale = new Set();

function currentView() {
  const v = location.hash.slice(1).split("/")[0];
  return v in VIEWS ? v : "home";
}

function showView() {
  const name = currentView();
  const { title, view } = VIEWS[name];
  $$("#nav a").forEach((a) => {
    const on = a.dataset.view === name;
    a.classList.toggle("on", on);
    if (on) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  $$(".view").forEach((s) => { s.hidden = s.dataset.view !== name; });
  $("#page-title").textContent = title;
  $("#page-actions").innerHTML = "";
  document.title = name === "home" ? "myWealth" : `${title} · myWealth`;
  const el = $(`#view-${name}`);
  if (!mounted.has(name)) {
    view.mount(el);
    mounted.add(name);
  }
  stale.delete(name);
  Promise.resolve(view.show(el, $("#page-actions"))).catch((e) => toast(e.message, true));
}

// Data changed somewhere: the visible view refreshes now, the others when shown.
onChange(() => {
  for (const name of mounted) stale.add(name);
  const name = currentView();
  if (stale.has(name)) {
    stale.delete(name);
    Promise.resolve(VIEWS[name].view.show($(`#view-${name}`), $("#page-actions"))).catch((e) => toast(e.message, true));
  }
});

// ------------------------------------------------------------------- theme --
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
const effectiveTheme = (t) => (t === "system" ? (systemDark.matches ? "dark" : "light") : t);

export function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  store("mw-theme", theme === "system" ? null : theme);
  $("#theme-label").textContent = `Tema: ${THEME_NAMES[theme] || THEME_NAMES.system}`;
  $$("[data-theme-choice]").forEach((b) => {
    const on = b.dataset.themeChoice === theme;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
  });
  window.dispatchEvent(new Event("mw-theme"));
}

export async function saveTheme(theme) {
  const previous = state.settings.theme;
  applyTheme(theme);
  try {
    state.settings = await api("PUT", "/api/settings", { theme });
  } catch (e) {
    applyTheme(previous);
    toast(e.message, true);
  }
}
window.addEventListener("mw-save-theme", (ev) => saveTheme(ev.detail));

// -------------------------------------------------------------------- exit --
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

// -------------------------------------------------------------------- init --
async function init() {
  const today = new Date().toLocaleDateString(LOCALE, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  $("#today").textContent = today;

  state.settings.theme = store("mw-theme") || "system";
  applyTheme(state.settings.theme);
  $("#btn-theme").addEventListener("click", () => {
    saveTheme(effectiveTheme(state.settings.theme) === "dark" ? "light" : "dark");
  });
  $("#btn-exit").addEventListener("click", exitApp);
  systemDark.addEventListener("change", () => window.dispatchEvent(new Event("mw-theme")));

  try {
    const [settings, status, currencies] = await Promise.all([
      api("GET", "/api/settings"), api("GET", "/api/status"), api("GET", "/api/currencies"), loadAccounts(), loadRates(),
    ]);
    state.settings = settings;
    state.status = status;
    state.currencies = currencies;
    applyTheme(settings.theme);
    $("#demo-banner").hidden = !status.demo;
  } catch (e) {
    toast(e.message, true);
  }
  window.addEventListener("hashchange", showView);
  showView();
  watchFx();
}

// Rates download in the background at startup: refresh the views when it ends.
async function watchFx() {
  for (let i = 0; i < 60 && state.fx && state.fx.running; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    try { await loadRates(); } catch (e) { return; }
    if (!state.fx.running) changed("fx");
  }
}

init();
