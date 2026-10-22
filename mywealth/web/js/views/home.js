/* Home: accounts table (M1). */
import {
  $, $$, api, changed, confirmDialog, dateFmt, esc, formData, ICON, inputNum, loadAccounts, money, openDialog,
  options, state, toast, todayISO,
} from "../core.js";

let root;

function mount(el) {
  root = el;
  el.innerHTML = `
    <div class="section-head">
      <h2 class="section-title">Conti</h2>
      <div class="row-actions">
        <label class="check"><input type="checkbox" id="show-archived"> Mostra archiviati</label>
        <button class="btn btn-primary" id="btn-new-account" type="button">${ICON.plus}Nuovo conto</button>
      </div>
    </div>
    <div class="card table-card"><div id="accounts-table"></div></div>`;
  $("#btn-new-account", el).addEventListener("click", () => accountDialog());
  $("#show-archived", el).addEventListener("change", renderTable);
}

async function show() {
  await loadAccounts();
  renderTable();
}

function renderTable() {
  const showArchived = $("#show-archived", root).checked;
  const list = state.accounts.filter((a) => showArchived || !a.archived);
  const box = $("#accounts-table", root);
  if (!list.length) {
    box.innerHTML = `<div class="empty-row">${state.accounts.length ? "Nessun conto attivo." : "Nessun conto: crea il primo con “Nuovo conto”."}</div>`;
    return;
  }
  box.innerHTML = `
    <table class="table">
      <thead><tr>
        <th>Nome</th><th class="hide-sm">Banca</th><th>Valuta</th><th class="hide-sm">Tipo</th>
        <th class="hide-md">Apertura</th><th class="num">Saldo</th><th class="actions"></th>
      </tr></thead>
      <tbody>${list.map(row).join("")}</tbody>
    </table>`;
  $$("[data-act]", box).forEach((b) => b.addEventListener("click", () => act(b.dataset.act, Number(b.dataset.id))));
}

function row(a) {
  return `<tr class="${a.archived ? "muted-row" : ""}">
    <td><div class="cell-main">${esc(a.name)}</div>${a.archived ? '<span class="pill">archiviato</span>' : ""}</td>
    <td class="hide-sm">${esc(a.bank) || "—"}</td>
    <td>${esc(a.currency)}</td>
    <td class="hide-sm">${esc(a.type_name)}</td>
    <td class="hide-md">${dateFmt(a.opened_on)}</td>
    <td class="num ${Number(a.balance) < 0 ? "neg" : ""}">${money(a.balance, a.currency)}</td>
    <td class="actions">
      <button class="icon-btn" title="Modifica" data-act="edit" data-id="${a.id}">${ICON.edit}</button>
      <button class="icon-btn" title="${a.archived ? "Ripristina" : "Archivia"}" data-act="archive" data-id="${a.id}">${a.archived ? ICON.unarchive : ICON.archive}</button>
      ${a.movements ? "" : `<button class="icon-btn danger" title="Elimina" data-act="delete" data-id="${a.id}">${ICON.trash}</button>`}
    </td>
  </tr>`;
}

async function act(what, id) {
  const a = state.accounts.find((x) => x.id === id);
  if (!a) return;
  try {
    if (what === "edit") return accountDialog(a);
    if (what === "archive") {
      if (!a.archived && !(await confirmDialog("Archivia conto",
        `“${esc(a.name)}” sparirà dalle selezioni ma resterà nello storico e nei report. Potrai ripristinarlo in ogni momento.`,
        { confirmLabel: "Archivia", danger: false }))) return;
      await api("PUT", `/api/accounts/${id}`, { archived: !a.archived });
      toast(a.archived ? "Conto ripristinato" : "Conto archiviato");
    }
    if (what === "delete") {
      if (!(await confirmDialog("Elimina conto", `Eliminare definitivamente “${esc(a.name)}”?`, { confirmLabel: "Elimina" }))) return;
      await api("DELETE", `/api/accounts/${id}`);
      toast("Conto eliminato");
    }
    await loadAccounts();
    changed("accounts");
  } catch (e) {
    toast(e.message, true);
  }
}

export function accountDialog(a = null) {
  const types = state.types.filter((t) => !t.archived || (a && t.id === a.type_id));
  const lockCurrency = a && a.movements > 0;
  return openDialog({
    title: a ? "Modifica conto" : "Nuovo conto",
    render(body) {
      body.innerHTML = `
        <div class="grid2">
          <label class="field span2">Nome<input name="name" required maxlength="80" value="${esc(a?.name)}" autocomplete="off"></label>
          <label class="field">Banca<input name="bank" maxlength="80" value="${esc(a?.bank)}" autocomplete="off"></label>
          <label class="field">Tipo<select name="type_id">${options(types, a?.type_id)}</select></label>
          <label class="field">Valuta
            <select name="currency" ${lockCurrency ? "disabled" : ""}>${options(state.currencies, a?.currency || "EUR", (c) => `${c.code} · ${c.name}`, (c) => c.code)}</select>
            ${lockCurrency ? '<span class="hint">Non modificabile: il conto ha operazioni.</span>' : ""}
          </label>
          <label class="field">Data di apertura<input name="opened_on" type="date" max="${todayISO()}" value="${a?.opened_on || todayISO()}"></label>
          <label class="field span2">Saldo iniziale alla data di apertura
            <div class="input-unit"><input name="opening_balance" inputmode="decimal" value="${a ? inputNum(a.opening_balance) : ""}" placeholder="0,00" autocomplete="off"><span class="unit" data-unit></span></div>
          </label>
          <label class="field span2">Note<textarea name="notes" rows="2" maxlength="1000">${esc(a?.notes)}</textarea></label>
        </div>`;
      const cur = $('[name="currency"]', body);
      const unit = $("[data-unit]", body);
      const sync = () => { unit.textContent = cur.value; };
      cur.addEventListener("change", sync);
      sync();
    },
    async onSubmit(form) {
      const data = formData(form);
      const saved = a ? await api("PUT", `/api/accounts/${a.id}`, data) : await api("POST", "/api/accounts", data);
      await loadAccounts();
      changed("accounts");
      toast(a ? "Conto aggiornato" : "Conto creato");
      return saved;
    },
  });
}

export default { mount, show };
