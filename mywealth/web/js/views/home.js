/* Home: accounts table (M1). */
import {
  $, $$, api, changed, confirmDialog, dateFmt, esc, formData, ICON, inputNum, loadAccounts, loadRates, money, num,
  openDialog, options, rateNote, state, toast, toEur, todayISO,
} from "../core.js";
import { manualRateDialog } from "./settings.js";
import { savingsDialog } from "./savings.js";

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
    <div class="card table-card"><div id="accounts-table"></div></div>
    <div class="fx-bar" id="fx-bar"></div>`;
  $("#btn-new-account", el).addEventListener("click", () => accountDialog());
  $("#show-archived", el).addEventListener("change", renderTable);
}

async function show() {
  await Promise.all([loadAccounts(), loadRates()]);
  renderTable();
  renderFx();
}

function renderFx() {
  const box = $("#fx-bar", root);
  const fx = state.fx;
  const curs = Object.keys(fx.rates);
  if (!curs.length) { box.innerHTML = ""; return; }
  const items = curs.map((c) => {
    const r = fx.rates[c];
    if (!r.rate) return `<span class="fx-item warn">${c}: <button class="link" data-manual="${c}">inserisci tasso</button></span>`;
    const title = `1 ${c} = ${num(r.rate, 6)} EUR · ${r.source === "manual" ? "manuale" : "Yahoo"} del ${dateFmt(r.date)}`;
    return `<span class="fx-item ${r.stale ? "warn" : ""}" title="${esc(title)}">${c} ${num(r.rate, 4)}${r.stale ? ` <span class="muted">(${dateFmt(r.date)})</span>` : ""}</span>`;
  });
  const status = fx.offline ? '<span class="pill warn">offline</span>' : fx.running ? '<span class="pill">aggiornamento…</span>' : "";
  box.innerHTML = `<span class="muted">Cambi in EUR</span> ${items.join("")} ${status}
    <button class="icon-btn" id="fx-refresh" title="Aggiorna i cambi" ${fx.offline ? "disabled" : ""}>${ICON.refresh}</button>`;
  $$("[data-manual]", box).forEach((b) => b.addEventListener("click", () => manualRateDialog(b.dataset.manual)));
  const btn = $("#fx-refresh", box);
  btn.addEventListener("click", async () => {
    btn.classList.add("spinning");
    btn.disabled = true;
    try {
      const res = await api("POST", "/api/fx/refresh");
      const errs = Object.values((res.last && res.last.result && res.last.result.errors) || {});
      if (errs.length) toast(`Cambi non aggiornati: ${errs[0]}`, true);
      else toast("Cambi aggiornati");
      changed("fx");
    } catch (e) {
      toast(e.message, true);
      btn.classList.remove("spinning");
      btn.disabled = false;
    }
  });
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
  $$("[data-manual]", box).forEach((b) => b.addEventListener("click", () => manualRateDialog(b.dataset.manual)));
}

function row(a) {
  return `<tr class="${a.archived ? "muted-row" : ""}">
    <td><div class="cell-main">${esc(a.name)}</div>${a.archived ? '<span class="pill">archiviato</span>' : ""}${a.behavior === "savings" && a.annual_rate != null ? `<span class="pill rate">${num(a.annual_rate, 4)}%</span>` : ""}</td>
    <td class="hide-sm">${esc(a.bank) || "—"}</td>
    <td>${esc(a.currency)}</td>
    <td class="hide-sm">${esc(a.type_name)}</td>
    <td class="hide-md">${dateFmt(a.opened_on)}</td>
    <td class="num"><span class="${Number(a.balance) < 0 ? "neg" : ""}">${money(a.balance, a.currency)}</span>${eurLine(a)}</td>
    <td class="actions">
      ${a.behavior === "savings" ? `<button class="icon-btn" title="Rendimento e interessi" data-act="savings" data-id="${a.id}">${ICON.percent}</button>` : ""}
      <button class="icon-btn" title="Modifica" data-act="edit" data-id="${a.id}">${ICON.edit}</button>
      <button class="icon-btn" title="${a.archived ? "Ripristina" : "Archivia"}" data-act="archive" data-id="${a.id}">${a.archived ? ICON.unarchive : ICON.archive}</button>
      ${a.movements ? "" : `<button class="icon-btn danger" title="Elimina" data-act="delete" data-id="${a.id}">${ICON.trash}</button>`}
    </td>
  </tr>`;
}

function eurLine(a) {
  if (a.currency === "EUR") return "";
  const eur = toEur(a.balance, a.currency);
  const note = rateNote(a.currency);
  if (eur == null) return `<div class="cell-sub"><button class="link" data-manual="${a.currency}">tasso mancante</button></div>`;
  return `<div class="cell-sub">= ${money(eur, "EUR")}${note ? ` · ${esc(note)}` : ""}</div>`;
}

async function act(what, id) {
  const a = state.accounts.find((x) => x.id === id);
  if (!a) return;
  try {
    if (what === "edit") return accountDialog(a);
    if (what === "savings") return savingsDialog(a);
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
          ${a ? "" : `<label class="field span2" data-rate-field hidden>Rendimento annuo % (facoltativo)
            <input name="annual_rate" inputmode="decimal" autocomplete="off" placeholder="es. 2,5">
            <span class="hint">Gli interessi maturano dalla data di apertura. Potrai cambiare il tasso in seguito.</span></label>`}
          <label class="field span2">Note<textarea name="notes" rows="2" maxlength="1000">${esc(a?.notes)}</textarea></label>
        </div>`;
      const cur = $('[name="currency"]', body);
      const unit = $("[data-unit]", body);
      const sync = () => { unit.textContent = cur.value; };
      cur.addEventListener("change", sync);
      sync();
      const typeSel = $('[name="type_id"]', body), rateField = $("[data-rate-field]", body);
      const syncType = () => {
        if (!rateField) return;
        const t = state.types.find((x) => x.id === Number(typeSel.value));
        rateField.hidden = !t || t.behavior !== "savings";
      };
      typeSel.addEventListener("change", syncType);
      syncType();
    },
    async onSubmit(form) {
      const data = formData(form);
      const rate = data.annual_rate;
      delete data.annual_rate;
      const saved = a ? await api("PUT", `/api/accounts/${a.id}`, data) : await api("POST", "/api/accounts", data);
      if (!a && rate && saved.behavior === "savings") {
        try {
          await api("POST", `/api/savings/${saved.id}/rates`, { annual_rate: rate, valid_from: saved.opened_on });
        } catch (e) {
          toast(`Conto creato, ma il rendimento non è stato salvato: ${e.message}`, true);
        }
      }
      await loadAccounts();
      changed("accounts");
      toast(a ? "Conto aggiornato" : "Conto creato");
      return saved;
    },
  });
}

export default { mount, show };
