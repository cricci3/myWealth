/* Settings: theme, account types, information. */
import { exportAll, importAll, restoreBackup } from "../transfer.js";
import {
  $, $$, api, BEHAVIOR_NAMES, changed, confirmDialog, dateFmt, download, esc, formData, ICON, loadAccounts, loadCategories,
  loadRates, num, openDialog, options, state, toast, todayISO,
} from "../core.js";

const NATURES = { expense: "Spese", income: "Entrate", transfer: "Trasferimenti" };

let root;

function mount(el) {
  root = el;
  el.innerHTML = `
    <div class="card settings">
      <div class="setting">
        <div>
          <div class="setting-name">Tema</div>
          <div class="setting-hint">“Sistema” segue il tema di Windows.</div>
        </div>
        <div class="segmented" id="theme-choice" role="radiogroup" aria-label="Tema">
          <button type="button" role="radio" data-theme-choice="system">Sistema</button>
          <button type="button" role="radio" data-theme-choice="light">Chiaro</button>
          <button type="button" role="radio" data-theme-choice="dark">Scuro</button>
        </div>
      </div>
      <div class="setting">
        <div>
          <div class="setting-name">Formato dei numeri</div>
          <div class="setting-hint">Le date sono sempre gg/mm/aaaa. Negli importi puoi sempre scrivere sia 1.234,56 sia 1234.56.</div>
        </div>
        <select class="input auto-w" data-setting-select="number_format" data-reload aria-label="Formato dei numeri">
          <option value="it-IT">1.234,56 (italiano)</option><option value="en-GB">1,234.56 (inglese)</option>
        </select>
      </div>
      <div class="setting">
        <div>
          <div class="setting-name">Avvia con importi oscurati</div>
          <div class="setting-hint">All'apertura gli importi sono nascosti (•••••) anche se l'ultima volta erano visibili. Li mostri con l'occhio in alto o con Ctrl+Shift+H.</div>
        </div>
        <label class="switch"><input type="checkbox" data-setting="start_amounts_hidden" aria-label="Avvia con importi oscurati"><span></span></label>
      </div>
      <div class="setting">
        <div>
          <div class="setting-name">Periodo del grafico in Home</div>
          <div class="setting-hint">Quello mostrato all'apertura; puoi cambiarlo dalla Home in ogni momento.</div>
        </div>
        <select class="input auto-w" data-setting-select="home_range" aria-label="Periodo predefinito">
          <option value="30">30 giorni</option><option value="60">60 giorni</option><option value="90">90 giorni</option><option value="max">Tutto</option>
        </select>
      </div>
    </div>

    <div class="section-head">
      <h2 class="section-title">Cambi valuta</h2>
      <div class="row-actions">
        <button class="btn btn-sm" type="button" id="btn-fx-manual">${ICON.plus}Tasso manuale</button>
        <button class="btn btn-sm" type="button" id="btn-fx-refresh">${ICON.refresh}Aggiorna ora</button>
      </div>
    </div>
    <div class="card settings">
      <div class="setting">
        <div>
          <div class="setting-name">Modalità offline</div>
          <div class="setting-hint">Nessuna connessione a Yahoo Finance: si usano gli ultimi tassi e prezzi salvati.</div>
        </div>
        <label class="switch"><input type="checkbox" data-setting="offline_mode" aria-label="Modalità offline"><span></span></label>
      </div>
      <div class="setting">
        <div>
          <div class="setting-name">Aggiorna i cambi all'avvio</div>
          <div class="setting-hint">Al massimo una richiesta al giorno per valuta; Yahoo riceve solo le coppie valutarie e le date.</div>
        </div>
        <label class="switch"><input type="checkbox" data-setting="fx_auto_refresh" aria-label="Aggiorna i cambi all'avvio"><span></span></label>
      </div>
    </div>
    <div class="card table-card gap-top"><div id="fx-table"></div></div>

    <h2 class="section-title">Salvadanaio</h2>
    <div class="card settings">
      <div class="setting">
        <div>
          <div class="setting-name">Ritenuta fiscale sugli interessi</div>
          <div class="setting-hint">Gli interessi mensili vengono accreditati al netto della ritenuta (in Italia 26%).</div>
        </div>
        <div class="row-actions">
          <div class="input-unit small-input"><input class="input" id="tax-rate" inputmode="decimal" aria-label="Aliquota ritenuta"><span class="unit">%</span></div>
          <label class="switch"><input type="checkbox" data-setting="interest_tax_enabled" aria-label="Applica la ritenuta"><span></span></label>
        </div>
      </div>
    </div>

    <div class="section-head">
      <h2 class="section-title">Tipi di conto</h2>
      <button class="btn btn-sm" type="button" id="btn-new-type">${ICON.plus}Nuovo tipo</button>
    </div>
    <div class="card table-card"><div id="types-table"></div></div>

    <div class="section-head">
      <h2 class="section-title">Categorie</h2>
      <button class="btn btn-sm" type="button" id="btn-new-cat">${ICON.plus}Nuova categoria</button>
    </div>
    <div class="cat-grid" id="cat-grid"></div>

    <div class="section-head">
      <h2 class="section-title">Dati e backup</h2>
      <div class="row-actions">
        <button class="btn btn-sm" type="button" id="btn-export-all">Esporta tutto</button>
        <button class="btn btn-sm" type="button" id="btn-import-all">Importa tutto</button>
      </div>
    </div>
    <div class="card settings">
      <div class="setting">
        <div>
          <div class="setting-name">Cartella dati</div>
          <div class="setting-hint mono" id="data-dir"></div>
        </div>
        <button class="btn btn-sm" type="button" id="btn-open-dir">${ICON.folder}Apri cartella</button>
      </div>
      <div class="setting">
        <div>
          <div class="setting-name">Backup automatici da conservare</div>
          <div class="setting-hint">Un backup a ogni avvio, nello stesso formato di “Esporta tutto”.</div>
        </div>
        <input class="input small-num" type="number" min="1" max="100" id="backup-keep" aria-label="Numero di backup">
      </div>
    </div>
    <div class="section-head">
      <h3 class="section-title">Backup</h3>
      <button class="btn btn-sm" type="button" id="btn-backup-now">${ICON.plus}Backup ora</button>
    </div>
    <div class="card table-card"><div id="backups-table"></div></div>

    <h2 class="section-title">PIN di sblocco</h2>
    <div class="card settings">
      <div class="setting">
        <div>
          <div class="setting-name" id="pin-state">PIN</div>
          <div class="setting-hint">Chiede un PIN a ogni apertura di myWealth. Protegge l'app aperta, non cifra i dati sul disco (per quello serve BitLocker).</div>
        </div>
        <div class="row-actions">
          <button class="btn btn-sm" type="button" id="btn-pin">Imposta PIN</button>
          <button class="btn btn-sm btn-ghost" type="button" id="btn-pin-off" hidden>Rimuovi</button>
          <button class="btn btn-sm btn-ghost" type="button" id="btn-lock" hidden>Blocca ora</button>
        </div>
      </div>
    </div>

    <h2 class="section-title">Smartphone</h2>
    <div class="card settings">
      <div class="setting">
        <div>
          <div class="setting-name" id="mobile-state">Nessuno smartphone abbinato</div>
          <div class="setting-hint">Registra spese, entrate e trasferimenti dal telefono, anche senza rete: l'app myWealth per smartphone li invia cifrati in un file che importi qui.</div>
        </div>
        <div class="row-actions">
          <button class="btn btn-sm" type="button" id="btn-pair">Abbina smartphone</button>
          <button class="btn btn-sm btn-ghost" type="button" id="btn-rekey" hidden>Rigenera chiave</button>
        </div>
      </div>
      <div class="setting">
        <div>
          <div class="setting-name">Cartella in arrivo</div>
          <div class="setting-hint" id="inbox-hint">myWealth cerca qui i file arrivati dal telefono (<span class="mono">mywealth-….txt</span>); gli altri file non vengono mai letti.</div>
        </div>
        <label class="switch"><input type="checkbox" data-setting="mobile_inbox_enabled" aria-label="Cerca i file nella cartella in arrivo"><span></span></label>
      </div>
      <div class="setting" id="inbox-dir-row">
        <div>
          <div class="setting-name">Percorso della cartella</div>
          <div class="setting-hint">Lascia vuoto per usare la cartella Download.</div>
        </div>
        <input class="input" id="inbox-dir" aria-label="Percorso della cartella in arrivo" spellcheck="false">
      </div>
    </div>

    <h2 class="section-title">Avvio e finestra</h2>
    <div class="card settings">
      <div class="setting">
        <div>
          <div class="setting-name">Browser della finestra app</div>
          <div class="setting-hint" id="browser-hint">Finestra dedicata senza barra degli indirizzi (Brave, altrimenti Edge) o scheda del browser predefinito. Vale dalla prossima apertura.</div>
        </div>
        <select class="input auto-w" data-setting-select="app_browser" aria-label="Browser della finestra app">
          <option value="auto">Automatico</option><option value="brave">Brave</option><option value="edge">Edge</option><option value="default">Browser predefinito (scheda)</option>
        </select>
      </div>
      <div class="setting">
        <div>
          <div class="setting-name">Chiusura automatica</div>
          <div class="setting-hint">Il server si ferma quando nessuna finestra di myWealth è aperta da questo numero di minuti (0 = mai).</div>
        </div>
        <div class="input-unit small-input"><input class="input" type="number" min="0" max="1440" data-setting-num="idle_minutes" aria-label="Minuti"><span class="unit">min</span></div>
      </div>
      <div class="setting">
        <div>
          <div class="setting-name">Porta del server</div>
          <div class="setting-hint">Vale dal prossimo avvio; se è occupata si usa la successiva libera.</div>
        </div>
        <input class="input small-num" type="number" min="1024" max="65535" data-setting-num="port" aria-label="Porta">
      </div>
      <div data-shortcuts></div>
    </div>

    <h2 class="section-title">Informazioni</h2>
    <div class="card"><dl class="info" id="info"></dl></div>`;
  $$("[data-theme-choice]", el).forEach((b) =>
    b.addEventListener("click", () => window.dispatchEvent(new CustomEvent("mw-save-theme", { detail: b.dataset.themeChoice }))));
  $("#btn-new-type", el).addEventListener("click", () => typeDialog());
  $("#btn-new-cat", el).addEventListener("click", () => categoryDialog());
  $("#btn-fx-manual", el).addEventListener("click", () => manualRateDialog());
  $("#btn-pin", el).addEventListener("click", () => pinDialog(true));
  $("#btn-pair", el).addEventListener("click", () => pairDialog(false));
  $("#btn-rekey", el).addEventListener("click", async () => {
    const ok = await confirmDialog("Rigenera chiave",
      "Lo smartphone abbinato non potrà più inviare file finché non lo abbini di nuovo, e i file già cifrati con la vecchia chiave non si potranno importare. Usala se hai perso il telefono.",
      { confirmLabel: "Rigenera" });
    if (ok) pairDialog(true);
  });
  $("#inbox-dir", el).addEventListener("change", async (ev) => {
    try {
      state.settings = await api("PUT", "/api/settings", { mobile_inbox_dir: ev.target.value });
      toast("Cartella salvata");
      renderMobile();
    } catch (e) {
      ev.target.value = state.settings.mobile_inbox_dir;
      toast(e.message, true);
    }
  });
  $("#btn-pin-off", el).addEventListener("click", () => pinDialog(false));
  $("#btn-lock", el).addEventListener("click", () => api("POST", "/api/lock").then(() => location.reload()));
  $("#btn-export-all", el).addEventListener("click", () => exportAll().catch((e) => toast(e.message, true)));
  $("#btn-import-all", el).addEventListener("click", () => importAll());
  $("#btn-open-dir", el).addEventListener("click", () => api("POST", "/api/data-dir/open").catch((e) => toast(e.message, true)));
  $("#btn-backup-now", el).addEventListener("click", async () => {
    try {
      await api("POST", "/api/backups");
      toast("Backup creato");
      renderBackups();
    } catch (e) { toast(e.message, true); }
  });
  $("#backup-keep", el).addEventListener("change", async (ev) => {
    try {
      state.settings = await api("PUT", "/api/settings", { backup_keep: Number(ev.target.value) });
      toast("Impostazione salvata");
    } catch (e) {
      ev.target.value = state.settings.backup_keep;
      toast(e.message, true);
    }
  });
  $("#btn-fx-refresh", el).addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      const res = await api("POST", "/api/fx/refresh");
      const errs = Object.entries((res.last && res.last.result && res.last.result.errors) || {});
      toast(errs.length ? `${errs[0][0]}: ${errs[0][1]}` : "Cambi aggiornati", errs.length > 0);
      changed("fx");
    } catch (e) { toast(e.message, true); } finally { btn.disabled = false; }
  });
  $("#tax-rate", el).addEventListener("change", async (ev) => {
    const input = ev.currentTarget;
    try {
      state.settings = await api("PUT", "/api/settings", { interest_tax_rate: input.value });
      input.value = state.settings.interest_tax_rate.replace(".", ",");
      toast("Aliquota salvata: vale per i prossimi mesi calcolati");
    } catch (e) {
      input.value = String(state.settings.interest_tax_rate).replace(".", ",");
      toast(e.message, true);
    }
  });
  $$("[data-setting-num]", el).forEach((input) => input.addEventListener("change", async () => {
    const key = input.dataset.settingNum;
    try {
      state.settings = await api("PUT", "/api/settings", { [key]: Number(input.value) });
      toast("Impostazione salvata");
    } catch (e) {
      input.value = state.settings[key];
      toast(e.message, true);
    }
  }));
  $$("[data-setting-select]", el).forEach((sel) => sel.addEventListener("change", async () => {
    try {
      state.settings = await api("PUT", "/api/settings", { [sel.dataset.settingSelect]: sel.value });
      toast("Impostazione salvata");
      if (sel.dataset.settingSelect === "app_browser") renderBrowserHint();
      if ("reload" in sel.dataset) setTimeout(() => location.reload(), 500);
    } catch (e) {
      sel.value = state.settings[sel.dataset.settingSelect];
      toast(e.message, true);
    }
  }));
  $$("[data-setting]", el).forEach((input) => input.addEventListener("change", async () => {
    try {
      state.settings = await api("PUT", "/api/settings", { [input.dataset.setting]: input.checked });
      changed("settings");
    } catch (e) {
      input.checked = !input.checked;
      toast(e.message, true);
    }
  }));
}

async function show() {
  const theme = state.settings.theme || "system";
  $$("[data-theme-choice]", root).forEach((b) => {
    const on = b.dataset.themeChoice === theme;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
  });
  $$("[data-setting]", root).forEach((input) => { input.checked = !!state.settings[input.dataset.setting]; });
  $$("[data-setting-select]", root).forEach((sel) => { sel.value = state.settings[sel.dataset.settingSelect]; });
  $$("[data-setting-num]", root).forEach((input) => { input.value = state.settings[input.dataset.settingNum]; });
  renderShortcuts();
  renderPin();
  renderMobile();
  $("#tax-rate", root).value = String(state.settings.interest_tax_rate ?? "").replace(".", ",");
  await Promise.all([loadAccounts(), loadCategories(), loadRates()]);
  await renderFx();
  renderTypes();
  renderCategories();
  renderInfo();
  $("#backup-keep", root).value = state.settings.backup_keep;
  $("#data-dir", root).textContent = state.status ? state.status.data_dir : "";
  $("#btn-open-dir", root).hidden = !!(state.status && state.status.demo);
  await renderBackups();
}

async function renderPin() {
  const s = await api("GET", "/api/lock");
  $("#pin-state", root).textContent = s.pin_set ? "PIN attivo" : "PIN non impostato";
  $("#btn-pin", root).textContent = s.pin_set ? "Cambia PIN" : "Imposta PIN";
  $("#btn-pin-off", root).hidden = !s.pin_set;
  $("#btn-lock", root).hidden = !s.pin_set;
  root.dataset.pinSet = s.pin_set ? "1" : "";
}

function pinDialog(setting) {
  const hasPin = !!root.dataset.pinSet;
  return openDialog({
    title: setting ? (hasPin ? "Cambia PIN" : "Imposta PIN") : "Rimuovi PIN",
    submitLabel: setting ? "Salva" : "Rimuovi",
    danger: !setting,
    render(body) {
      body.innerHTML = `
        ${hasPin ? `<label class="field">PIN attuale<input name="current" type="password" inputmode="numeric" autocomplete="off" maxlength="12"></label>` : ""}
        ${setting ? `<label class="field">Nuovo PIN (4–12 cifre)<input name="new" type="password" inputmode="numeric" autocomplete="off" maxlength="12"></label>
        <label class="field">Ripeti il nuovo PIN<input name="again" type="password" inputmode="numeric" autocomplete="off" maxlength="12"></label>
        <p class="dlg-note">Se dimentichi il PIN non c'è modo di recuperarlo dall'app.</p>` : ""}`;
    },
    async onSubmit(form) {
      const d = formData(form);
      if (setting && d.new !== d.again) throw new Error("I due PIN non coincidono.");
      await api("PUT", "/api/pin", { current: d.current || "", new: setting ? d.new : "" });
      toast(setting ? "PIN salvato" : "PIN rimosso");
      await renderPin();
      return true;
    },
  });
}

// -------------------------------------------------------------- smartphone --
async function renderMobile() {
  let s;
  try { s = await api("GET", "/api/mobile"); } catch (e) { return; }
  $("#mobile-state", root).textContent = s.paired ? `Smartphone abbinato il ${dateFmt(s.created)}` : "Nessuno smartphone abbinato";
  $("#btn-pair", root).textContent = s.paired ? "Mostra QR configurazione" : "Abbina smartphone";
  $("#btn-rekey", root).hidden = !s.paired;
  $("#inbox-dir-row", root).hidden = !s.inbox.enabled;
  const dir = $("#inbox-dir", root);
  dir.value = state.settings.mobile_inbox_dir || "";
  dir.placeholder = s.inbox.custom ? "" : s.inbox.dir;
  $("#inbox-hint", root).innerHTML = s.inbox.enabled
    ? `All'avvio e ogni 2 minuti myWealth cerca in <span class="mono">${esc(s.inbox.dir)}</span> i file arrivati dal telefono (<span class="mono">mywealth-….txt</span>); gli altri file non vengono mai letti.${s.inbox.exists ? "" : ' <span class="warn-text">La cartella non esiste.</span>'}`
    : "Disattivata: importa i file dal telefono da Operazioni → Da smartphone.";
}

const QR_SECONDS = 120;
const MOBILE_URL = "https://cricci3.github.io/myWealth/"; // GitHub Pages, .github/workflows/pages.yml

/** QR with the key and the configuration (accounts, categories); hidden after 2 minutes. */
async function pairDialog(regenerate) {
  let data;
  try { data = await api("POST", "/api/mobile/pair", { regenerate }); } catch (e) { toast(e.message, true); return; }
  renderMobile();
  if (regenerate) toast("Nuova chiave creata: abbina di nuovo lo smartphone");
  let timer;
  await openDialog({
    title: "Abbina smartphone",
    cancelLabel: "Chiudi",
    render(body, { close }) {
      const n = data.qr.length;
      body.innerHTML = `
        <p class="dlg-note">Sul telefono apri l'app myWealth (la prima volta, in Chrome: <span class="mono">${MOBILE_URL}</span>, poi menu → Installa app) e tocca <b>Inquadra il codice</b> (in Impostazioni → <b>Aggiorna configurazione</b> se è già abbinato): inquadra ${n > 1 ? `i ${n} codici, uno alla volta e nell'ordine` : "il codice"}.
          Dopo aver aggiunto o modificato conti e categorie, mostra di nuovo questo codice per aggiornare il telefono.</p>
        <p class="dlg-note warn-text">Il codice contiene la chiave che protegge i dati inviati dal telefono: non fotografarlo e non condividerlo.</p>
        <div class="qr-box">
          <div class="qr-code" data-qr></div>
          <div class="qr-nav" ${n > 1 ? "" : "hidden"}>
            <button type="button" class="btn btn-sm" data-prev>Precedente</button>
            <span data-pos></span>
            <button type="button" class="btn btn-sm" data-next>Successivo</button>
          </div>
          <span class="muted small" data-left></span>
        </div>
        <details class="qr-details">
          <summary class="link">Il telefono non ha la fotocamera? Copia il codice come testo</summary>
          <textarea class="input qr-text" readonly data-text></textarea>
          <button type="button" class="btn btn-sm" data-copy>Copia</button>
        </details>`;
      let i = 0;
      const show = () => {
        $("[data-qr]", body).innerHTML = data.qr[i];
        $("[data-pos]", body).textContent = `${i + 1} di ${n}`;
        $("[data-prev]", body).disabled = i === 0;
        $("[data-next]", body).disabled = i === n - 1;
      };
      $("[data-prev]", body).addEventListener("click", () => { i = Math.max(0, i - 1); show(); });
      $("[data-next]", body).addEventListener("click", () => { i = Math.min(n - 1, i + 1); show(); });
      $("[data-text]", body).value = data.text;
      $("[data-copy]", body).addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(data.text); toast("Copiato: incollalo nell'app sul telefono"); } catch (e) { toast("Copia non riuscita: seleziona il testo e copialo.", true); }
      });
      show();
      const end = Date.now() + QR_SECONDS * 1000;
      const tick = () => {
        const left = Math.max(0, Math.round((end - Date.now()) / 1000));
        $("[data-left]", body).textContent = `Il codice si nasconde tra ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
        if (!left) close();
      };
      tick();
      timer = setInterval(tick, 1000);
    },
  });
  clearInterval(timer);
}

const SHORTCUTS = [
  ["start_menu", "Menu Start", "Apri myWealth scrivendo “myWealth” dopo aver premuto il tasto Windows; puoi fissarlo sulla barra delle applicazioni."],
  ["desktop", "Collegamento sul desktop", "Icona di myWealth sul desktop."],
  ["startup", "Avvia all'accesso a Windows", "Apre myWealth automaticamente quando accedi."],
];

let browsers = null;

const BROWSER_NAMES = { brave: "Brave", edge: "Microsoft Edge", default: "una scheda del browser predefinito" };

/** Which browser opens the app window with the current setting, and a warning if the chosen one is missing. */
function renderBrowserHint() {
  const hint = $("#browser-hint", root);
  if (!hint || !browsers) return;
  const choice = state.settings.app_browser;
  const order = { auto: ["brave", "edge"], brave: ["brave", "edge"], edge: ["edge"], default: [] }[choice] || [];
  const used = order.find((b) => browsers[b]) || "default";
  const missing = choice === "brave" || choice === "edge" ? (browsers[choice] ? "" : `${BROWSER_NAMES[choice]} non è installato: `) : "";
  hint.textContent = `${missing}la finestra si apre con ${BROWSER_NAMES[used]}${used === "default" ? "" : ", senza barra degli indirizzi"}. Vale dalla prossima apertura.`;
  hint.classList.toggle("warn-text", Boolean(missing));
}

async function renderShortcuts() {
  const box = $("[data-shortcuts]", root);
  let sys;
  try { sys = await api("GET", "/api/system"); } catch (e) { return; }
  browsers = sys.browsers;
  renderBrowserHint();
  if (!sys.shortcuts.supported || sys.demo) { box.innerHTML = ""; return; }
  box.innerHTML = SHORTCUTS.map(([k, name, hint]) => `
    <div class="setting">
      <div><div class="setting-name">${name}</div><div class="setting-hint">${hint}</div></div>
      <label class="switch"><input type="checkbox" data-shortcut="${k}" ${sys.shortcuts[k] ? "checked" : ""} aria-label="${name}"><span></span></label>
    </div>`).join("") + (sys.shortcuts.gui_executable ? "" : `<p class="dlg-note">mywealth-gui non trovato nell'ambiente: i collegamenti useranno uno script VBS che avvia “uv run”.</p>`);
  $$("[data-shortcut]", box).forEach((input) => input.addEventListener("change", async () => {
    input.disabled = true;
    try {
      await api("POST", "/api/shortcuts", { kind: input.dataset.shortcut, create: input.checked });
      toast(input.checked ? "Collegamento creato" : "Collegamento rimosso");
    } catch (e) {
      input.checked = !input.checked;
      toast(e.message, true);
    } finally { input.disabled = false; }
  }));
}

const fmtSize = (n) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1).replace(".", ",")} MB`);

async function renderBackups() {
  const box = $("#backups-table", root);
  const res = await api("GET", "/api/backups");
  if (!res.items.length) {
    box.innerHTML = `<div class="empty-row">Nessun backup ancora: il primo viene creato al prossimo avvio (o con “Backup ora”).</div>`;
    return;
  }
  const reason = (n) => (n.includes("pre-import") ? "prima di un import" : n.includes("manual") ? "manuale" : "automatico");
  box.innerHTML = `<table class="table">
    <thead><tr><th>Data</th><th class="hide-sm">Tipo</th><th class="num">Dimensione</th><th class="actions"></th></tr></thead>
    <tbody>${res.items.map((b) => `<tr>
      <td>${dateFmt(b.created_at.slice(0, 10))} ${b.created_at.slice(11, 16)}</td><td class="hide-sm">${reason(b.name)}</td>
      <td class="num">${fmtSize(b.size)}</td>
      <td class="actions"><button class="btn btn-sm btn-ghost" type="button" data-restore="${esc(b.name)}">Ripristina</button>
        <button class="icon-btn" type="button" title="Scarica" data-dl="${esc(b.name)}">${ICON.download}</button></td></tr>`).join("")}
    </tbody></table>`;
  box.querySelectorAll("[data-restore]").forEach((btn) => btn.addEventListener("click", () =>
    restoreBackup(res.items.find((x) => x.name === btn.dataset.restore))));
  box.querySelectorAll("[data-dl]").forEach((btn) => btn.addEventListener("click", () =>
    download(`/api/backups/${encodeURIComponent(btn.dataset.dl)}`, btn.dataset.dl).catch((e) => toast(e.message, true))));
}

const SOURCES = { yahoo: "Yahoo", manual: "Manuale", demo: "Demo" };

async function renderFx() {
  const box = $("#fx-table", root);
  $("#btn-fx-refresh", root).disabled = !!state.settings.offline_mode;
  const rates = Object.entries(state.fx.rates);
  const manual = await api("GET", "/api/fx/rates");
  if (!rates.length && !manual.length) {
    box.innerHTML = `<div class="empty-row">Tutti i conti sono in EUR: nessun cambio necessario.</div>`;
    return;
  }
  const statusOf = (r) => r.error
    ? `<span class="neg small" title="${esc(r.error)}">errore ultimo aggiornamento</span>`
    : r.stale ? '<span class="muted small">non aggiornato</span>' : '<span class="pos small">aggiornato</span>';
  box.innerHTML = `
    <table class="table">
      <thead><tr><th>Valuta</th><th class="num">1 unità in EUR</th><th>Data</th><th class="hide-sm">Fonte</th><th class="hide-md">Stato</th></tr></thead>
      <tbody>${rates.map(([c, r]) => `
        <tr><td><div class="cell-main">${c}</div></td>
          <td class="num">${r.rate ? num(r.rate, 6) : `<button class="link" data-manual="${c}">inserisci</button>`}</td>
          <td>${r.date ? dateFmt(r.date) : "—"}</td>
          <td class="hide-sm">${SOURCES[r.source] || "—"}</td>
          <td class="hide-md">${statusOf(r)}</td>
        </tr>`).join("")}</tbody>
    </table>
    ${manual.length ? `
    <table class="table manual-table">
      <thead><tr><th>Tassi manuali</th><th class="num">1 unità in EUR</th><th>Data</th><th class="actions"></th></tr></thead>
      <tbody>${manual.map((r) => `
        <tr><td>${r.currency}</td><td class="num">${num(r.rate, 6)}</td><td>${dateFmt(r.date)}</td>
          <td class="actions"><button class="icon-btn danger" title="Elimina" data-del-rate="${r.currency}/${r.date}">${ICON.trash}</button></td></tr>`).join("")}
      </tbody>
    </table>` : ""}`;
  $$("[data-manual]", box).forEach((b) => b.addEventListener("click", () => manualRateDialog(b.dataset.manual)));
  $$("[data-del-rate]", box).forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("DELETE", `/api/fx/rates/${b.dataset.delRate}`);
      changed("fx");
    } catch (e) { toast(e.message, true); }
  }));
}

/** Enter an exchange rate by hand (no connection, or a currency Yahoo doesn't know). */
export function manualRateDialog(currency = null) {
  const curs = state.currencies.filter((c) => c.code !== "EUR");
  const initial = currency || Object.keys(state.fx.rates)[0] || "USD";
  return openDialog({
    title: "Tasso di cambio manuale",
    render(body) {
      body.innerHTML = `
        <div class="grid2">
          <label class="field">Valuta<select name="currency">${options(curs, initial, (c) => `${c.code} · ${c.name}`, (c) => c.code)}</select></label>
          <label class="field">Data<input type="date" name="date" max="${todayISO()}" value="${todayISO()}"></label>
          <label class="field">Espresso come<select name="direction">
            <option value="to_eur">1 valuta = x EUR</option><option value="per_eur">1 EUR = x valuta</option></select></label>
          <label class="field">Tasso<input name="rate" inputmode="decimal" autocomplete="off" placeholder="es. 1,0650"></label>
        </div>
        <p class="dlg-note">I tassi manuali hanno la precedenza su Yahoo per lo stesso giorno. Le operazioni senza controvalore EUR lo ricevono subito.</p>`;
    },
    async onSubmit(form) {
      const saved = await api("POST", "/api/fx/rates", formData(form));
      await loadRates();
      changed("fx");
      toast("Tasso salvato");
      return saved;
    },
  });
}

function renderTypes() {
  const box = $("#types-table", root);
  box.innerHTML = `
    <table class="table">
      <thead><tr><th>Nome</th><th>Comportamento</th><th class="num">Conti</th><th class="actions"></th></tr></thead>
      <tbody>${state.types.map((t) => `
        <tr class="${t.archived ? "muted-row" : ""}">
          <td><div class="cell-main">${esc(t.name)}</div>${t.builtin ? '<span class="pill">predefinito</span>' : ""}${t.archived ? '<span class="pill">archiviato</span>' : ""}</td>
          <td>${BEHAVIOR_NAMES[t.behavior]}</td>
          <td class="num">${t.used}</td>
          <td class="actions">
            <button class="icon-btn" title="Modifica" data-act="edit" data-id="${t.id}">${ICON.edit}</button>
            ${t.builtin ? "" : `<button class="icon-btn" title="${t.archived ? "Ripristina" : "Archivia"}" data-act="archive" data-id="${t.id}">${t.archived ? ICON.unarchive : ICON.archive}</button>`}
            ${t.builtin || t.used ? "" : `<button class="icon-btn danger" title="Elimina" data-act="delete" data-id="${t.id}">${ICON.trash}</button>`}
          </td>
        </tr>`).join("")}</tbody>
    </table>`;
  $$("[data-act]", box).forEach((b) => b.addEventListener("click", async () => {
    const t = state.types.find((x) => x.id === Number(b.dataset.id));
    try {
      if (b.dataset.act === "edit") return typeDialog(t);
      if (b.dataset.act === "archive") await api("PUT", `/api/account-types/${t.id}`, { archived: !t.archived });
      if (b.dataset.act === "delete") {
        if (!(await confirmDialog("Elimina tipo", `Eliminare il tipo “${esc(t.name)}”?`, { confirmLabel: "Elimina" }))) return;
        await api("DELETE", `/api/account-types/${t.id}`);
      }
      await loadAccounts();
      changed("types");
    } catch (e) {
      toast(e.message, true);
    }
  }));
}

function typeDialog(t = null) {
  const lock = t && (t.builtin || t.used > 0);
  return openDialog({
    title: t ? "Modifica tipo di conto" : "Nuovo tipo di conto",
    render(body) {
      body.innerHTML = `
        <label class="field">Nome<input name="name" maxlength="80" value="${esc(t?.name)}" autocomplete="off"></label>
        <label class="field">Comportamento
          <select name="behavior" ${lock ? "disabled" : ""}>
            ${Object.entries(BEHAVIOR_NAMES).map(([k, v]) => `<option value="${k}" ${t?.behavior === k ? "selected" : ""}>${v}</option>`).join("")}
          </select>
          <span class="hint">${lock ? "Non modificabile: tipo predefinito o già usato." : "Salvadanaio abilita il rendimento annuo, Investimenti gli asset."}</span>
        </label>`;
    },
    async onSubmit(form) {
      const data = formData(form);
      const saved = t ? await api("PUT", `/api/account-types/${t.id}`, data) : await api("POST", "/api/account-types", data);
      await loadAccounts();
      changed("types");
      return saved;
    },
  });
}

function renderCategories() {
  const box = $("#cat-grid", root);
  box.innerHTML = Object.entries(NATURES).map(([nature, label]) => `
    <div class="card table-card"><div>
      <table class="table">
        <thead><tr><th>${label}</th><th class="num">Usi</th><th class="actions"></th></tr></thead>
        <tbody>${state.categories.filter((c) => c.nature === nature).map((c) => `
          <tr class="${c.archived ? "muted-row" : ""}">
            <td><div class="cell-main">${esc(c.name)}</div>${c.archived ? '<span class="pill">archiviata</span>' : ""}</td>
            <td class="num">${c.used}</td>
            <td class="actions">
              <button class="icon-btn" title="Rinomina" data-act="edit" data-id="${c.id}">${ICON.edit}</button>
              ${c.system_key ? "" : `
              <button class="icon-btn" title="${c.archived ? "Ripristina" : "Archivia"}" data-act="archive" data-id="${c.id}">${c.archived ? ICON.unarchive : ICON.archive}</button>
              <button class="icon-btn danger" title="Elimina" data-act="delete" data-id="${c.id}">${ICON.trash}</button>`}
            </td>
          </tr>`).join("")}</tbody>
      </table></div></div>`).join("");
  $$("[data-act]", box).forEach((b) => b.addEventListener("click", async () => {
    const c = state.categories.find((x) => x.id === Number(b.dataset.id));
    try {
      if (b.dataset.act === "edit") return categoryDialog(c);
      if (b.dataset.act === "archive") await api("PUT", `/api/categories/${c.id}`, { archived: !c.archived });
      if (b.dataset.act === "delete") {
        if (!(await deleteCategoryDialog(c))) return;
      }
      await loadCategories();
      changed("categories");
    } catch (e) {
      toast(e.message, true);
    }
  }));
}

function categoryDialog(c = null) {
  return openDialog({
    title: c ? "Rinomina categoria" : "Nuova categoria",
    render(body) {
      body.innerHTML = `
        <label class="field">Nome<input name="name" maxlength="60" value="${esc(c?.name)}" autocomplete="off"></label>
        ${c ? "" : `<label class="field">Natura<select name="nature">
          ${Object.entries(NATURES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>`}`;
    },
    async onSubmit(form) {
      const data = formData(form);
      const saved = c ? await api("PUT", `/api/categories/${c.id}`, data) : await api("POST", "/api/categories", data);
      await loadCategories();
      changed("categories");
      return saved;
    },
  });
}

function deleteCategoryDialog(c) {
  if (!c.used) {
    return confirmDialog("Elimina categoria", `Eliminare la categoria “${esc(c.name)}”?`, { confirmLabel: "Elimina" })
      .then((ok) => ok && api("DELETE", `/api/categories/${c.id}`));
  }
  const others = state.categories.filter((x) => x.nature === c.nature && x.id !== c.id && !x.archived);
  return openDialog({
    title: "Elimina categoria",
    submitLabel: "Sposta ed elimina",
    danger: true,
    render(body) {
      body.innerHTML = `
        <p class="dlg-text">“${esc(c.name)}” è usata da ${c.used} operazion${c.used === 1 ? "e" : "i"}. Scegli la categoria in cui spostarle.</p>
        <label class="field" style="margin-top:12px">Sposta in<select name="move_to">${options(others)}</select></label>`;
    },
    async onSubmit(form) {
      await api("DELETE", `/api/categories/${c.id}?move_to=${encodeURIComponent(form.elements.move_to.value)}`);
      return true;
    },
  });
}

function renderInfo() {
  const s = state.status;
  if (!s) return;
  const rows = [
    ["Versione", esc(s.version)],
    ["Modalità", s.demo ? "Demo (database temporaneo)" : "Normale"],
    ["Cartella dati", `<span class="mono">${esc(s.data_dir)}</span>`],
    ["Schema database", `v${esc(s.schema_version)}`],
  ];
  $("#info", root).innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}


export default { mount, show };
