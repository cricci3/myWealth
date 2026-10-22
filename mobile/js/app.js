/* myWealth smartphone (SPEC §16): offline entry of expenses, income and transfers, kept in
 * IndexedDB and sent to the PC only as an AES-256-GCM encrypted file. No network calls. */
import { encryptFile, importKey } from "./crypto.js";
import { buildCsv, exportFileName, formatAmount, parseAmount } from "./csv.js";
import { ChunkCollector, PairingError, parsePayload } from "./pairing.js";
import { canScan, startScan } from "./scanner.js";
import * as store from "./store.js";

export const APP_VERSION = "1.1.0"; // keep in sync with VERSION in sw.js
const REMIND_DAYS = 7;
const KEEP_EXPORTED_DAYS = 30;
const KINDS = { expense: "Spesa", income: "Entrata", transfer: "Trasferimento" };
const SAVED = { expense: "Spesa salvata", income: "Entrata salvata", transfer: "Trasferimento salvato" };
const NATURE_NAMES = { expense: "spese", income: "entrate", transfer: "trasferimenti" };
const TITLES = { pair: "Abbina", new: "Nuova voce", list: "Voci", export: "Esporta", settings: "Impostazioni" };

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const todayISO = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
const dateFmt = (iso) => { const [y, m, d] = String(iso).slice(0, 10).split("-"); return `${d}/${m}/${y}`; };
const dateTimeFmt = (iso) => new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const daysAgo = (iso) => (Date.now() - new Date(iso).getTime()) / 86400000;
const MASK = "•••••"; // hidden amount in "Voci" (eye button); the currency stays visible
const svg = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const ICON = {
  edit: svg('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/>'),
  trash: svg('<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>'),
};

const app = {
  pairing: null, // {cryptoKey, kid, at, pairedAt, accounts, categories}
  prefs: { theme: "system", last: {}, hideAmounts: false },
  entries: [],
  screen: "new",
  editing: null, // entry being edited
  kind: "expense",
  dirty: false, // an entry is being typed: never reload for an update now
  stopScan: null,
};

// ------------------------------------------------------------------- utils --
let toastTimer;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("err", isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), isError ? 5000 : 2500);
}

function confirmBox(title, text, okLabel, danger = true) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.innerHTML = `<h3>${esc(title)}</h3><p>${esc(text)}</p>
      <div class="actions"><button type="button" class="btn" data-no>Annulla</button>
      <button type="button" class="btn ${danger ? "btn-danger" : "btn-primary"}" data-yes>${esc(okLabel)}</button></div>`;
    document.body.appendChild(dlg);
    let answer = false;
    $("[data-no]", dlg).addEventListener("click", () => dlg.close());
    $("[data-yes]", dlg).addEventListener("click", () => { answer = true; dlg.close(); });
    dlg.addEventListener("close", () => { dlg.remove(); resolve(answer); });
    dlg.showModal();
  });
}

const account = (name) => (app.pairing?.accounts || []).find((a) => a.name === name);
const pending = () => app.entries.filter((e) => e.status === "pending");
const exported = () => app.entries.filter((e) => e.status === "exported");
const byNewest = (a, b) => (b.date + b.createdAt).localeCompare(a.date + a.createdAt);

async function savePrefs() {
  await store.setValue("prefs", app.prefs);
}

/** Delete a pending entry after confirmation: it will not be exported. True if deleted. */
async function removeEntry(e) {
  if (!(await confirmBox("Eliminare la voce?", "La voce viene cancellata dal telefono e non sarà esportata.", "Elimina"))) return false;
  await store.deleteEntry(e.id);
  app.entries = app.entries.filter((x) => x.id !== e.id);
  updateCount();
  toast("Voce eliminata");
  return true;
}

// Amounts in "Voci" can be hidden (eye button in the header); the choice is kept in prefs.
function applyMask() {
  const on = Boolean(app.prefs.hideAmounts), btn = $("#btn-mask"), label = on ? "Mostra importi" : "Nascondi importi";
  btn.setAttribute("aria-pressed", String(on));
  btn.setAttribute("aria-label", label);
  btn.title = label;
}

function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  try { if (theme === "light" || theme === "dark") localStorage.setItem("mw-theme", theme); else localStorage.removeItem("mw-theme"); } catch (e) { /* private mode */ }
}

// ------------------------------------------------------------------ router --
function show(screen) {
  if (app.stopScan) { app.stopScan(); app.stopScan = null; }
  if (!app.pairing && screen !== "pair") screen = "pair";
  app.screen = screen;
  $$(".screen").forEach((s) => { s.hidden = s.id !== `screen-${screen}`; });
  $("#tabbar").hidden = !app.pairing;
  $$("[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === screen));
  $("#title").textContent = screen === "new" && app.editing ? "Modifica voce" : TITLES[screen];
  $("#btn-mask").hidden = screen !== "list";
  ({ pair: renderPair, new: renderNew, list: renderList, export: renderExport, settings: renderSettings })[screen]();
  window.scrollTo(0, 0);
}

function updateCount() {
  const n = pending().length;
  const el = $("#pending-count");
  el.hidden = n === 0;
  el.textContent = String(n);
}

// ----------------------------------------------------------------- pairing --
function renderPair() {
  const el = $("#screen-pair");
  const updating = Boolean(app.pairing);
  el.innerHTML = `
    <div class="card">
      <ol class="steps">
        <li>Sul PC apri myWealth: <b>Impostazioni → Smartphone → ${updating ? "Mostra QR configurazione" : "Abbina smartphone"}</b>.</li>
        <li>Inquadra il codice QR${updating ? " per aggiornare conti e categorie" : ""}. Se sono più codici, inquadrali uno alla volta.</li>
      </ol>
    </div>
    <div class="scan-box" data-scan hidden><video muted playsinline></video><div class="frame"></div></div>
    <p class="note" data-progress hidden></p>
    ${canScan() ? `<button type="button" class="btn btn-primary btn-block" data-start>Inquadra il codice</button>` : `<p class="note">La fotocamera non è disponibile in questo browser: copia il codice come testo dal PC e incollalo qui sotto.</p>`}
    <label class="field">Oppure incolla il codice copiato dal PC
      <textarea class="input" data-text spellcheck="false" autocapitalize="off" autocomplete="off"></textarea></label>
    <button type="button" class="btn btn-block" data-paste>Abbina con il testo</button>
    ${updating ? `<button type="button" class="btn btn-ghost" data-cancel>Annulla</button>` : ""}
    <p class="error" data-error hidden></p>`;
  const chunks = new ChunkCollector();
  const err = $("[data-error]", el);
  const fail = (msg) => { err.textContent = msg; err.hidden = !msg; };

  const accept = async (text) => {
    fail("");
    try {
      if (ChunkCollector.isChunk(text)) {
        const full = chunks.add(text);
        const p = $("[data-progress]", el);
        p.hidden = false;
        p.textContent = `Codici letti: ${chunks.count} di ${chunks.total}`;
        if (!full) return;
        text = full;
      }
      await pair(text);
    } catch (e) {
      fail(e instanceof PairingError ? e.message : `Abbinamento non riuscito: ${e.message}`);
    }
  };
  $("[data-start]", el)?.addEventListener("click", async (ev) => {
    ev.currentTarget.hidden = true;
    $("[data-scan]", el).hidden = false;
    try {
      app.stopScan = await startScan($("video", el), accept);
    } catch (e) {
      $("[data-scan]", el).hidden = true;
      fail(e.message);
    }
  });
  $("[data-paste]", el).addEventListener("click", () => {
    const text = $("[data-text]", el).value.trim();
    if (!text) { fail("Incolla prima il codice copiato dal PC."); return; }
    // Pasted multi-part text: one code per line.
    const lines = text.split(/\s*\n\s*/).filter(Boolean);
    if (lines.every((l) => ChunkCollector.isChunk(l))) { lines.forEach((l) => accept(l)); return; }
    accept(text);
  });
  $("[data-cancel]", el)?.addEventListener("click", () => show("settings"));
}

async function pair(text) {
  const data = await parsePayload(text);
  const cryptoKey = await importKey(data.key); // non-extractable from now on
  const changedKey = app.pairing && app.pairing.kid !== data.kid;
  app.pairing = { cryptoKey, kid: data.kid, at: data.at, pairedAt: new Date().toISOString(), accounts: data.accounts, categories: data.categories };
  await store.setValue("pairing", app.pairing);
  if (app.stopScan) { app.stopScan(); app.stopScan = null; }
  const nc = Object.values(data.categories).reduce((n, l) => n + l.length, 0);
  toast(`${changedKey === false ? "Configurazione aggiornata" : "Abbinato"}: ${data.accounts.length} conti, ${nc} categorie`);
  show("new");
}

// --------------------------------------------------------------- new entry --
function accountOptions(selected) {
  return app.pairing.accounts.map((a) => `<option value="${esc(a.name)}"${a.name === selected ? " selected" : ""}>${esc(a.name)} · ${esc(a.currency)}</option>`).join("");
}

function categoryOptions(nature, selected) {
  const list = app.pairing.categories[nature] || [];
  const none = nature === "transfer" ? `<option value="">Nessuna</option>` : "";
  return none + list.map((c) => `<option${c === selected ? " selected" : ""}>${esc(c)}</option>`).join("");
}

function reminderHtml(link = true) {
  const old = pending().filter((e) => daysAgo(e.createdAt) > REMIND_DAYS);
  const text = `${old.length === 1 ? "Una voce non è stata esportata" : `${old.length} voci non sono state esportate`} da più di ${REMIND_DAYS} giorni`;
  if (!old.length) return "";
  return link ? `<button type="button" class="banner" data-remind>${text}: esportale ora.</button>` : `<p class="banner">${text}.</p>`;
}

function renderNew() {
  const el = $("#screen-new");
  const e = app.editing;
  const kind = e ? e.kind : app.kind;
  const last = app.prefs.last[kind] || {};
  const accs = app.pairing.accounts;
  if (!accs.length) {
    el.innerHTML = `<div class="card empty">Nessun conto nella configurazione. Crea un conto sul PC, poi aggiorna la configurazione dalle Impostazioni.</div>`;
    return;
  }
  const from = e ? e.from : last.from && account(last.from) ? last.from : accs[0].name;
  const to = e ? e.to : last.to && account(last.to) ? last.to : (accs.find((a) => a.name !== from) || accs[0]).name;
  const cat = e ? e.category : last.category;
  el.innerHTML = `
    ${e ? "" : reminderHtml()}
    <div class="seg" role="tablist" aria-label="Tipo">${Object.entries(KINDS).map(([k, v]) => `<button type="button" role="tab" data-kind="${k}" class="${k === kind ? "on" : ""}" aria-selected="${k === kind}" ${e && k !== kind ? "disabled" : ""}>${v}</button>`).join("")}</div>
    <form class="screen" data-form novalidate autocomplete="off">
      <label class="field">Importo
        <span class="amount"><input class="input" name="amount" inputmode="decimal" enterkeyhint="done" placeholder="0,00" value="${esc(e ? String(e.amount).replace(".", ",") : "")}"><span class="cur" data-cur></span></span></label>
      ${kind === "transfer" ? `
        <div class="row2">
          <label class="field">Da<select class="input" name="from">${accountOptions(from)}</select></label>
          <label class="field">A<select class="input" name="to">${accountOptions(to)}</select></label>
        </div>
        <label class="field" data-received>Importo ricevuto
          <span class="amount"><input class="input" name="toAmount" inputmode="decimal" placeholder="0,00" value="${esc(e?.toAmount ? String(e.toAmount).replace(".", ",") : "")}"><span class="cur" data-cur-to></span></span></label>`
    : `<label class="field">Conto<select class="input" name="${kind === "income" ? "to" : "from"}">${accountOptions(kind === "income" ? to : from)}</select></label>`}
      <label class="field">Categoria<select class="input" name="category">${categoryOptions(kind, cat)}</select></label>
      <div class="row2">
        <label class="field">Data<input class="input" type="date" name="date" max="${todayISO()}" value="${e ? e.date : todayISO()}"></label>
        <label class="field">Descrizione<input class="input" name="description" maxlength="200" enterkeyhint="done" value="${esc(e ? e.description : "")}"></label>
      </div>
      <p class="error" data-error hidden></p>
      <button type="submit" class="btn btn-primary btn-block">${e ? "Salva modifiche" : `Salva ${KINDS[kind].toLowerCase()}`}</button>
      ${e ? `<div class="actions"><button type="button" class="btn btn-ghost" data-cancel>Annulla</button><button type="button" class="btn btn-danger" data-delete>Elimina</button></div>` : ""}
    </form>`;
  const form = $("[data-form]", el);
  const f = form.elements;
  const sync = () => {
    const src = account(kind === "income" ? f.to.value : f.from.value);
    $("[data-cur]", el).textContent = src ? src.currency : "";
    if (kind === "transfer") {
      const dst = account(f.to.value);
      $("[data-cur-to]", el).textContent = dst ? dst.currency : "";
      $("[data-received]", el).hidden = !src || !dst || src.currency === dst.currency;
    }
  };
  sync();
  form.addEventListener("change", sync);
  form.addEventListener("input", () => { app.dirty = Boolean(f.amount.value || f.description.value); });
  $("[data-remind]", el)?.addEventListener("click", () => show("export"));
  $$("[data-kind]", el).forEach((b) => b.addEventListener("click", () => {
    if (e || b.dataset.kind === kind) return;
    app.kind = b.dataset.kind;
    const amount = f.amount.value;
    renderNew();
    $('[name="amount"]', el).value = amount; // keep what was typed when switching type
  }));
  $("[data-cancel]", el)?.addEventListener("click", () => { app.editing = null; app.dirty = false; show("list"); });
  $("[data-delete]", el)?.addEventListener("click", async () => {
    if (!(await removeEntry(e))) return;
    app.editing = null;
    app.dirty = false;
    show("list");
  });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = $("[data-error]", el);
    try {
      const entry = readEntry(kind, f, e);
      await store.putEntry(entry);
      app.entries = app.entries.filter((x) => x.id !== entry.id).concat(entry);
      app.prefs.last[kind] = { from: entry.from, to: entry.to, category: entry.category };
      await savePrefs();
      app.dirty = false;
      updateCount();
      if (e) {
        app.editing = null;
        toast("Voce modificata");
        show("list");
      } else {
        toast(SAVED[kind]);
        renderNew();
        $('[name="amount"]', el).focus();
      }
    } catch (x) {
      err.textContent = x.message;
      err.hidden = false;
    }
  });
  if (!e) f.amount.focus({ preventScroll: true });
}

function readEntry(kind, f, original) {
  const src = account(kind === "income" ? f.to.value : f.from.value);
  if (!src) throw new Error("Scegli il conto.");
  const amount = parseAmount(f.amount.value, src.decimals);
  const date = f.date.value;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error("Inserisci la data.");
  if (date > todayISO()) throw new Error("La data non può essere nel futuro.");
  const category = f.category.value;
  if (kind !== "transfer" && !category) throw new Error("Scegli la categoria.");
  const entry = {
    id: original ? original.id : crypto.randomUUID(),
    createdAt: original ? original.createdAt : new Date().toISOString(),
    status: "pending",
    kind, date, amount, category,
    description: f.description.value.trim().replace(/\s+/g, " "),
    from: kind === "income" ? "" : f.from.value,
    to: kind === "expense" ? "" : f.to.value,
    toAmount: "",
  };
  if (kind === "transfer") {
    if (entry.from === entry.to) throw new Error("Scegli due conti diversi.");
    const dst = account(entry.to);
    if (dst.currency !== src.currency) {
      try { entry.toAmount = parseAmount(f.toAmount.value, dst.decimals); } catch (x) { throw new Error(`Importo ricevuto: ${x.message}`); }
    }
  }
  return entry;
}

// -------------------------------------------------------------------- list --
function entryHtml(e, readonly) {
  const acc = e.kind === "income" ? e.to : e.from;
  const cur = account(acc)?.currency || "";
  const dec = account(acc)?.decimals ?? 2;
  const sign = e.kind === "expense" ? "−" : e.kind === "income" ? "+" : "";
  const where = e.kind === "transfer" ? `${e.from} → ${e.to}` : acc;
  const amount = app.prefs.hideAmounts ? MASK : formatAmount(e.amount, dec);
  return `<div class="entry${readonly ? " readonly" : ""}">
    <button type="button" class="entry-body" ${readonly ? "disabled" : `data-edit="${esc(e.id)}"`}>
      <span class="what">${esc(e.description || e.category || KINDS[e.kind])}</span>
      <span class="amt ${e.kind}">${sign}${amount} ${esc(cur)}</span>
      <span class="meta">${dateFmt(e.date)} · ${esc(where)}${e.category && e.description ? ` · ${esc(e.category)}` : ""}</span>
    </button>
    ${readonly ? "" : `<div class="entry-actions">
      <button type="button" class="icon-btn" data-edit="${esc(e.id)}" aria-label="Modifica" title="Modifica">${ICON.edit}</button>
      <button type="button" class="icon-btn danger" data-delete="${esc(e.id)}" aria-label="Elimina" title="Elimina">${ICON.trash}</button>
    </div>`}
  </div>`;
}

function renderList() {
  const el = $("#screen-list");
  const open = pending().sort(byNewest);
  const done = exported().sort(byNewest);
  const batches = new Map();
  for (const e of done) {
    if (!batches.has(e.exportedAt)) batches.set(e.exportedAt, []);
    batches.get(e.exportedAt).push(e);
  }
  const ordered = [...batches.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  el.innerHTML = `
    <h2>Da esportare · ${open.length}</h2>
    ${open.length ? `<div class="entries">${open.map((e) => entryHtml(e, false)).join("")}</div>` : `<div class="card empty">Nessuna voce in sospeso.</div>`}
    <h2>Esportate</h2>
    ${ordered.length ? ordered.map(([at, list]) => `
      <div class="batch-head"><span class="small muted">${dateTimeFmt(at)} · ${list.length} voc${list.length === 1 ? "e" : "i"}</span>
        <button type="button" class="btn btn-sm" data-resend="${esc(at)}">Esporta di nuovo</button></div>
      <div class="entries">${list.map((e) => entryHtml(e, true)).join("")}</div>`).join("")
      + `<p class="note small">Le voci esportate si cancellano da sole dopo ${KEEP_EXPORTED_DAYS} giorni. Reimportare lo stesso file sul PC non crea doppioni.</p>
        <button type="button" class="btn btn-danger" data-clear>Svuota esportate</button>`
    : `<div class="card empty">Nessuna voce esportata negli ultimi ${KEEP_EXPORTED_DAYS} giorni.</div>`}`;
  $$("[data-edit]", el).forEach((b) => b.addEventListener("click", () => {
    app.editing = app.entries.find((x) => x.id === b.dataset.edit);
    show("new");
  }));
  $$("[data-delete]", el).forEach((b) => b.addEventListener("click", async () => {
    const e = app.entries.find((x) => x.id === b.dataset.delete);
    if (e && (await removeEntry(e))) renderList();
  }));
  $$("[data-resend]", el).forEach((b) => b.addEventListener("click", () => exportEntries(batches.get(b.dataset.resend), b)));
  $("[data-clear]", el)?.addEventListener("click", async () => {
    if (!(await confirmBox("Svuotare le esportate?", "Le voci già esportate vengono cancellate dal telefono. Quelle da esportare restano.", "Svuota"))) return;
    await store.deleteEntries(exported().map((e) => e.id));
    app.entries = pending();
    toast("Voci esportate cancellate");
    renderList();
  });
}

// ------------------------------------------------------------------ export --
function renderExport() {
  const el = $("#screen-export");
  const n = pending().length;
  el.innerHTML = `
    ${reminderHtml(false)}
    <div class="card stat"><span class="big">${n}</span><span class="muted">voc${n === 1 ? "e" : "i"} da esportare</span></div>
    <button type="button" class="btn btn-primary btn-block" data-export ${n ? "" : "disabled"}>Esporta e invia</button>
    <div class="card">
      <ol class="steps">
        <li>Si apre il menu di condivisione: scegli <b>Gmail</b> e invia la mail a te stesso.</li>
        <li>Sul PC scarica l'allegato: myWealth lo trova nella cartella Download e lo importa.</li>
      </ol>
    </div>
    <p class="note small">Il file è cifrato con la chiave dell'abbinamento: chi lo vede (anche il servizio di posta) non può leggere importi, conti o descrizioni. Dopo l'import puoi eliminare la mail.</p>`;
  $("[data-export]", el).addEventListener("click", (ev) => exportEntries(pending(), ev.currentTarget));
}

async function exportEntries(list, button) {
  if (!list || !list.length) return;
  button.disabled = true;
  try {
    const rows = [...list].sort((a, b) => (a.date + a.createdAt).localeCompare(b.date + b.createdAt));
    const text = await encryptFile(buildCsv(rows), app.pairing.cryptoKey, app.pairing.kid);
    const name = exportFileName();
    const file = new File([text], name, { type: "text/plain" });
    let how = "shared";
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: "myWealth export", text: "myWealth export" });
      } catch (e) {
        if (e.name === "AbortError") { toast("Invio annullato: le voci restano da esportare."); return; }
        how = "downloaded"; // sharing refused by the browser: save the file instead
      }
    } else {
      how = "downloaded";
    }
    if (how === "downloaded") {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(file);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
    }
    const at = new Date().toISOString();
    const marked = list.map((e) => ({ ...e, status: "exported", exportedAt: at }));
    await store.putEntries(marked);
    const ids = new Set(marked.map((e) => e.id));
    app.entries = app.entries.filter((e) => !ids.has(e.id)).concat(marked);
    updateCount();
    toast(how === "shared" ? `${marked.length} voc${marked.length === 1 ? "e esportata" : "i esportate"}`
      : `File ${name} salvato: allegalo a una mail per te stesso.`);
    show(app.screen);
  } catch (e) {
    toast(`Esportazione non riuscita: ${e.message}`, true);
  } finally {
    button.disabled = false;
  }
}

// ---------------------------------------------------------------- settings --
async function renderSettings() {
  const el = $("#screen-settings");
  const p = app.pairing;
  const nc = Object.entries(p.categories).map(([k, l]) => `${l.length} ${NATURE_NAMES[k]}`).join(", ");
  const persisted = await store.persist();
  el.innerHTML = `
    <h2>Abbinamento</h2>
    <div class="card screen">
      <dl class="kv">
        <dt>Configurazione del</dt><dd>${dateTimeFmt(p.at)}</dd>
        <dt>Conti</dt><dd>${p.accounts.length}</dd>
        <dt>Categorie</dt><dd>${nc}</dd>
        <dt>Chiave</dt><dd class="mono">${esc(p.kid)}</dd>
      </dl>
      <div class="actions">
        <button type="button" class="btn" data-update>Aggiorna configurazione</button>
        <button type="button" class="btn btn-danger" data-unpair>Rimuovi abbinamento</button>
      </div>
    </div>
    <h2>Tema</h2>
    <div class="seg" role="radiogroup" aria-label="Tema">${[["system", "Sistema"], ["light", "Chiaro"], ["dark", "Scuro"]].map(([k, v]) =>
      `<button type="button" role="radio" data-theme="${k}" class="${app.prefs.theme === k ? "on" : ""}" aria-checked="${app.prefs.theme === k}">${v}</button>`).join("")}</div>
    <h2>Dati sul telefono</h2>
    <div class="card"><p class="note">${persisted ? "Le voci sono salvate solo su questo telefono e il browser non le cancella per fare spazio."
      : "Le voci sono salvate solo su questo telefono. Il browser potrebbe cancellarle se manca spazio: installa l'app (menu di Chrome → Installa app) ed esporta spesso."}</p></div>
    <p class="note small muted">myWealth per smartphone ${APP_VERSION} · funziona offline, nessun dato lascia il telefono se non cifrato.</p>`;
  $("[data-update]", el).addEventListener("click", () => show("pair"));
  $("[data-unpair]", el).addEventListener("click", async () => {
    const n = pending().length;
    const ok = await confirmBox("Rimuovere l'abbinamento?",
      `Chiave e configurazione vengono cancellate da questo telefono.${n ? ` Le ${n} voci da esportare restano, ma potrai esportarle solo dopo un nuovo abbinamento.` : ""}`, "Rimuovi");
    if (!ok) return;
    await store.deleteValue("pairing");
    app.pairing = null;
    toast("Abbinamento rimosso");
    show("pair");
  });
  $$("[data-theme]", el).forEach((b) => b.addEventListener("click", async () => {
    app.prefs.theme = b.dataset.theme;
    applyTheme(app.prefs.theme);
    await savePrefs();
    renderSettings();
  }));
}

// ----------------------------------------------------------------- updates --
// A new version is installed in the background but used only when the user taps
// "Aggiorna", and never while an entry is being typed.
function watchUpdates() {
  if (!("serviceWorker" in navigator)) return;
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (reloading) location.reload(); });
  navigator.serviceWorker.register("sw.js").then((reg) => {
    const offer = () => { if (reg.waiting && navigator.serviceWorker.controller) $("#update").hidden = false; };
    offer();
    reg.addEventListener("updatefound", () => {
      const w = reg.installing;
      if (w) w.addEventListener("statechange", () => { if (w.state === "installed") offer(); });
    });
    $("#btn-update").addEventListener("click", () => {
      if (app.dirty) { toast("Salva o svuota l'inserimento in corso, poi aggiorna.", true); return; }
      if (!reg.waiting) { location.reload(); return; }
      reloading = true;
      reg.waiting.postMessage("SKIP_WAITING");
    });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) reg.update().catch(() => {}); });
  }).catch(() => { /* offline first load or unsupported: the app still works */ });
}

// -------------------------------------------------------------------- init --
async function init() {
  $("#btn-mask").addEventListener("click", async () => {
    app.prefs.hideAmounts = !app.prefs.hideAmounts;
    applyMask();
    if (app.screen === "list") renderList();
    await savePrefs();
  });
  $$("[data-tab]").forEach((b) => b.addEventListener("click", () => {
    if (app.screen === "new" && app.editing && b.dataset.tab !== "new") app.editing = null;
    show(b.dataset.tab);
  }));
  try {
    const [pairing, prefs, entries] = await Promise.all([store.getValue("pairing"), store.getValue("prefs"), store.allEntries()]);
    app.pairing = pairing || null;
    app.prefs = { theme: "system", last: {}, hideAmounts: false, ...(prefs || {}) };
    // Exported entries are kept 30 days for "Esporta di nuovo", then removed.
    const expired = entries.filter((e) => e.status === "exported" && daysAgo(e.exportedAt) > KEEP_EXPORTED_DAYS);
    if (expired.length) await store.deleteEntries(expired.map((e) => e.id));
    app.entries = entries.filter((e) => !expired.includes(e));
  } catch (e) {
    toast(`Archivio del telefono non disponibile: ${e.message}`, true);
  }
  applyTheme(app.prefs.theme);
  applyMask();
  updateCount();
  store.persist();
  show(app.pairing ? "new" : "pair");
  watchUpdates();
}

init();
