/* Settings: theme, account types, information. */
import {
  $, $$, api, BEHAVIOR_NAMES, changed, confirmDialog, esc, formData, ICON, loadAccounts, loadCategories, openDialog,
  options, state, toast,
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
}

async function show() {
  const theme = state.settings.theme || "system";
  $$("[data-theme-choice]", root).forEach((b) => {
    const on = b.dataset.themeChoice === theme;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
  });
  await Promise.all([loadAccounts(), loadCategories()]);
  renderTypes();
  renderCategories();
  renderInfo();
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
