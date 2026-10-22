/* Settings: theme, account types, information. */
import {
  $, $$, api, BEHAVIOR_NAMES, changed, confirmDialog, dateFmt, esc, formData, ICON, loadAccounts, loadCategories,
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

    <h2 class="section-title">Informazioni</h2>
    <div class="card"><dl class="info" id="info"></dl></div>`;
  $$("[data-theme-choice]", el).forEach((b) =>
    b.addEventListener("click", () => window.dispatchEvent(new CustomEvent("mw-save-theme", { detail: b.dataset.themeChoice }))));
  $("#btn-new-type", el).addEventListener("click", () => typeDialog());
  $("#btn-new-cat", el).addEventListener("click", () => categoryDialog());
  $("#btn-fx-manual", el).addEventListener("click", () => manualRateDialog());
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
  $$("[data-setting-select]", el).forEach((sel) => sel.addEventListener("change", async () => {
    try {
      state.settings = await api("PUT", "/api/settings", { [sel.dataset.settingSelect]: sel.value });
      toast("Impostazione salvata");
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
  $("#tax-rate", root).value = String(state.settings.interest_tax_rate ?? "").replace(".", ",");
  await Promise.all([loadAccounts(), loadCategories(), loadRates()]);
  await renderFx();
  renderTypes();
  renderCategories();
  renderInfo();
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
