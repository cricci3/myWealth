/* myWealth — shared helpers: API access, formatting, parsing, dialogs, toasts. */

export const TOKEN = document.querySelector('meta[name="mywealth-token"]').content;
export const LOCALE = "it-IT"; // texts and dates are always Italian
/** Number format (setting): it-IT "1.234,56" or en-GB "1,234.56". */
export let NUM_LOCALE = "it-IT";
export function setNumberLocale(loc) { NUM_LOCALE = loc === "en-GB" ? "en-GB" : "it-IT"; }
export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];

// ------------------------------------------------------------------- storage --
export function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch (e) { return null; }
  return null;
}

// ----------------------------------------------------------------------- api --
export async function api(method, path, body) {
  const isRaw = body instanceof Blob || body instanceof ArrayBuffer;
  const headers = { "X-MyWealth-Token": TOKEN };
  if (body !== undefined && !isRaw) headers["Content-Type"] = "application/json";
  if (isRaw) headers["Content-Type"] = "application/octet-stream";
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : isRaw ? body : JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty response */ }
  if (!res.ok) {
    const err = new Error(data.error || `Errore ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/** Download a file served by the API (token in the header, so no plain link). */
export async function download(path, fallbackName) {
  const res = await fetch(path, { headers: { "X-MyWealth-Token": TOKEN } });
  if (!res.ok) {
    let msg = `Errore ${res.status}`;
    try { msg = (await res.json()).error || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = /filename="([^"]+)"/.exec(cd);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// ---------------------------------------------------------------- formatting --
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtCache = {};
function moneyFormatter(cur, dec) {
  const k = `${NUM_LOCALE}|${cur}|${dec}`;
  if (!fmtCache[k]) {
    const opts = { style: "currency", currency: cur, currencyDisplay: "code", useGrouping: "always" };
    if (dec != null) { opts.minimumFractionDigits = dec; opts.maximumFractionDigits = dec; }
    fmtCache[k] = new Intl.NumberFormat(NUM_LOCALE, opts);
  }
  return fmtCache[k];
}

/** "1234.5" + "EUR" -> "1.234,50 EUR" (display only: amounts arrive as decimal strings). */
export function money(value, cur = "EUR", dec) {
  if (value == null || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!isFinite(n)) return "—";
  // "currencyDisplay: code" puts the code before or after depending on the locale: normalise
  const parts = moneyFormatter(cur, dec).formatToParts(n);
  const numStr = parts.filter((p) => p.type !== "currency" && p.type !== "literal").map((p) => p.value).join("");
  return `${numStr} ${cur}`;
}

export const signedMoney = (v, cur, dec) => {
  if (v == null) return "—";
  const n = Number(v);
  return (n > 0 ? "+" : n < 0 ? "−" : "") + money(Math.abs(n), cur, dec);
};

export function num(value, maxDec = 2, minDec = 0) {
  if (value == null || value === "") return "—";
  return Number(value).toLocaleString(NUM_LOCALE, { minimumFractionDigits: minDec, maximumFractionDigits: maxDec, useGrouping: "always" });
}

export const pct = (v, dec = 1) => (v == null || isNaN(v) ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") +
  Math.abs(v).toLocaleString(NUM_LOCALE, { minimumFractionDigits: dec, maximumFractionDigits: dec }) + "%");

export const tone = (v) => (v == null ? "" : Number(v) > 0 ? "pos" : Number(v) < 0 ? "neg" : "");

export const compact = (v) => new Intl.NumberFormat(NUM_LOCALE, { notation: "compact", maximumFractionDigits: 1 }).format(v);

export const dateFmt = (iso) => { if (!iso) return "—"; const [y, m, d] = iso.slice(0, 10).split("-"); return `${d}/${m}/${y}`; };
export const monthName = (ym) => new Date(ym + "-01T00:00:00").toLocaleDateString(LOCALE, { month: "long", year: "numeric" });
export const monthShort = (ym) => new Date(ym.slice(0, 7) + "-01T00:00:00").toLocaleDateString(LOCALE, { month: "short", year: "2-digit" });
export const todayISO = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
export const addDays = (iso, n) => { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };

/**
 * Same rules as money.parse_decimal() on the server: with both separators the last one
 * is the decimal mark; with one kind repeated it's thousands; a single one followed by
 * exactly three digits is thousands when `grouping` (amounts). Returns NaN if invalid.
 * Used for live previews only: the server parses (and validates) what is sent.
 */
export function parseNum(text, grouping = true) {
  let s = String(text ?? "").replace(/[\s'€$£  ]/g, "");
  if (!s) return NaN;
  const hasComma = s.includes(","), hasDot = s.includes(".");
  if (hasComma && hasDot) {
    const dec = s.lastIndexOf(",") > s.lastIndexOf(".") ? "," : ".";
    s = s.split(dec === "," ? "." : ",").join("").replace(",", ".");
  } else if (hasComma || hasDot) {
    const parts = s.split(hasComma ? "," : ".");
    const thousands = parts.length > 2 || (grouping && /^-?\d{1,3}$/.test(parts[0]) && /^\d{3}$/.test(parts[1]));
    s = thousands ? parts.join("") : parts.join(".");
  }
  return /^-?\d+(\.\d+)?$/.test(s) ? Number(s) : NaN;
}

/** Number -> text for an input field, Italian style without grouping ("1234,5"). */
export const inputNum = (v) => (v == null || v === "" ? "" : NUM_LOCALE === "it-IT" ? String(v).replace(".", ",") : String(v));

// --------------------------------------------------------------------- toast --
let toastTimer;
export function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("err", isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), isError ? 6000 : 2500);
}

// ------------------------------------------------------------------- dialogs --
/**
 * Open a modal dialog. `render(body)` fills it; `onSubmit(form)` runs on submit and may
 * throw to show an error inside the dialog. Resolves with onSubmit's result, or null.
 */
export function openDialog({ title, wide = false, render, onSubmit, submitLabel = "Salva", danger = false, cancelLabel = "Annulla" }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "dlg" + (wide ? " wide" : "");
    dlg.innerHTML = `
      <form method="dialog" class="dlg-form" novalidate>
        <header class="dlg-head"><h2>${esc(title)}</h2>
          <button type="button" class="icon-btn" data-close aria-label="Chiudi">${ICON.close}</button></header>
        <div class="dlg-body"></div>
        <div class="dlg-error" role="alert" hidden></div>
        <footer class="dlg-foot">
          <button type="button" class="btn btn-ghost" data-close>${esc(cancelLabel)}</button>
          ${onSubmit ? `<button type="submit" class="btn ${danger ? "btn-danger" : "btn-primary"}">${esc(submitLabel)}</button>` : ""}
        </footer>
      </form>`;
    document.body.appendChild(dlg);
    const form = $("form", dlg);
    const err = $(".dlg-error", dlg);
    let result = null;
    const close = () => { dlg.close(); };
    dlg.addEventListener("close", () => { dlg.remove(); resolve(result); });
    $$("[data-close]", dlg).forEach((b) => b.addEventListener("click", close));
    dlg.addEventListener("cancel", () => { result = null; });
    render($(".dlg-body", dlg), { dialog: dlg, showError, close });
    function showError(msg) { err.textContent = msg || ""; err.hidden = !msg; }
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (!onSubmit) return close();
      const btn = $('button[type="submit"]', dlg);
      btn.disabled = true;
      showError("");
      try {
        result = await onSubmit(form, { showError });
        if (result !== undefined && result !== false) close();
        else result = null;
      } catch (e) {
        showError(e.message);
      } finally {
        btn.disabled = false;
      }
    });
    dlg.showModal();
    const first = $("input:not([type=hidden]):not([readonly]), select, textarea", $(".dlg-body", dlg));
    if (first) first.focus();
  });
}

export function confirmDialog(title, message, { confirmLabel = "Conferma", danger = true } = {}) {
  return openDialog({
    title,
    submitLabel: confirmLabel,
    danger,
    render: (body) => { body.innerHTML = `<p class="dlg-text">${message}</p>`; },
    onSubmit: () => true,
  }).then((r) => r === true);
}

/** Read named fields of a form into an object (checkboxes -> booleans). */
export function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.type === "radio") { if (el.checked) out[el.name] = el.value; }
    else out[el.name] = el.value;
  }
  return out;
}

export const options = (items, selected, label = (x) => x.name, value = (x) => x.id) =>
  items.map((x) => `<option value="${esc(value(x))}"${String(value(x)) === String(selected) ? " selected" : ""}>${esc(label(x))}</option>`).join("");

// --------------------------------------------------------------------- icons --
const svg = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
export const ICON = {
  close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  edit: svg('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/>'),
  trash: svg('<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>'),
  archive: svg('<path d="M3 5h18v4H3zM5 9v10h14V9M10 13h4"/>'),
  unarchive: svg('<path d="M3 5h18v4H3zM5 9v10h14V9M12 17v-5m-2 2 2-2 2 2"/>'),
  refresh: svg('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>'),
  upload: svg('<path d="M12 16V5M7 10l5-5 5 5"/><path d="M5 20h14"/>'),
  download: svg('<path d="M12 4v11M7 10l5 5 5-5"/><path d="M5 20h14"/>'),
  more: svg('<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>'),
  warn: svg('<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>'),
  folder: svg('<path d="M3 6h6l2 2h10v11H3z"/>'),
  phone: svg('<rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 18h2"/>'),
  percent: svg('<path d="M19 5L5 19"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/>'),
};

// --------------------------------------------------------------- app state --
/** Shared cache of reference data (accounts, categories...), reloaded after changes. */
export const state = {
  settings: {},
  status: null,
  accounts: [],
  types: [],
  categories: [],
  currencies: [],
  rates: {},  // currency -> {rate, date, source}: latest EUR rates
};

const listeners = new Set();
export const onChange = (fn) => listeners.add(fn);
/** Signal that data changed: views re-render when they are shown. */
export function changed(what = "data") { listeners.forEach((fn) => fn(what)); }

export async function loadAccounts() {
  const [acc, types] = await Promise.all([api("GET", "/api/accounts"), api("GET", "/api/account-types")]);
  state.accounts = acc;
  state.types = types;
  return acc;
}

export const accountById = (id) => state.accounts.find((a) => a.id === Number(id));
export const activeAccounts = () => state.accounts.filter((a) => !a.archived);
export const curDecimals = (cur) => (state.currencies.find((c) => c.code === cur) || { decimals: 2 }).decimals;
export const BEHAVIOR_NAMES = { standard: "Standard", savings: "Salvadanaio", investment: "Investimenti" };

export async function loadCategories() {
  state.categories = await api("GET", "/api/categories");
  return state.categories;
}

/** Live "= Y EUR" next to an amount field, with the latest known rate (preview only). */
export function eurHint(el, value, cur, _date) {
  if (!cur || cur === "EUR" || !isFinite(value) || value === 0) { el.textContent = ""; return; }
  const r = (state.rates || {})[cur];
  if (!r || !r.rate) { el.textContent = "Controvalore EUR non disponibile"; return; }
  el.textContent = `= ${money(value * Number(r.rate), "EUR")}`;
}

export async function loadRates() {
  const res = await api("GET", "/api/fx");
  state.fx = res;
  state.rates = Object.fromEntries(Object.entries(res.rates).filter(([, r]) => r.rate));
  return res;
}

/** EUR value of an amount in `cur` with the latest rate, or null if unknown. */
export function toEur(value, cur) {
  if (value == null || value === "") return null;
  if (cur === "EUR") return Number(value);
  const r = state.rates[cur];
  return r ? Number(value) * Number(r.rate) : null;
}

/** Short note about the rate used for `cur`: "tasso del 20/10/2026", "offline", "manuale". */
export function rateNote(cur) {
  if (cur === "EUR") return "";
  const r = (state.fx && state.fx.rates[cur]) || null;
  if (!r || !r.rate) return "tasso non disponibile";
  const parts = [];
  if (state.fx.offline) parts.push("offline");
  if (r.stale || state.fx.offline || r.error) parts.push(`tasso del ${dateFmt(r.date)}`);
  if (r.source === "manual") parts.push("manuale");
  return parts.join(" · ");
}
