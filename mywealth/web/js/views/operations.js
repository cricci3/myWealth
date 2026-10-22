/* Operations: quick add buttons, filterable table, edit/delete. */
import {
  $, $$, accountById, activeAccounts, api, changed, confirmDialog, dateFmt, esc, eurHint, formData, ICON, inputNum,
  loadAccounts, loadCategories, money, openDialog, options, parseNum, state, toast, todayISO,
} from "../core.js";

import { csvImportDialog } from "../csvimport.js";

const KIND_LABELS = { expense: "Spesa", income: "Entrata", transfer: "Trasferimento", interest: "Interessi", fee: "Commissione", buy: "Acquisto", sell: "Vendita" };
const PAGE = 30;

let root;
const view = { items: [], offset: 0, hasMore: false, total: 0, filters: {} };

function mount(el) {
  root = el;
  el.innerHTML = `
    <div class="quick-add">
      <button class="btn btn-quick expense" type="button" data-new="expense">${ICON.plus}Spesa</button>
      <button class="btn btn-quick income" type="button" data-new="income">${ICON.plus}Entrata</button>
      <button class="btn btn-quick transfer" type="button" data-new="transfer">${ICON.plus}Trasferimento</button>
      <span class="spacer"></span>
      <button class="btn" type="button" id="btn-import">${ICON.upload}Importa CSV</button>
    </div>
    <details class="filters-wrap" id="filters-wrap">
    <summary class="btn btn-sm">Filtri</summary>
    <form class="filters card" id="tx-filters" autocomplete="off">
      <label class="field">Conto<select name="account"></select></label>
      <label class="field">Categoria<select name="category"></select></label>
      <label class="field">Tipo<select name="kind">
        <option value="">Tutti</option>
        ${Object.entries(KIND_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
      </select></label>
      <label class="field">Dal<input type="date" name="from"></label>
      <label class="field">Al<input type="date" name="to"></label>
      <label class="field grow">Cerca<input type="search" name="q" placeholder="Descrizione"></label>
      <button class="btn btn-ghost btn-sm reset" type="reset">Azzera</button>
    </form>
    </details>
    <div class="card table-card"><div id="tx-table"></div></div>
    <div class="load-more"><span class="muted" id="tx-count"></span>
      <button class="btn btn-sm" type="button" id="tx-more" hidden>Carica altre</button></div>`;
  const wrap = $("#filters-wrap", el);
  wrap.open = window.innerWidth > 560;
  window.addEventListener("resize", () => { if (window.innerWidth > 560) wrap.open = true; });
  $$("[data-new]", el).forEach((b) => b.addEventListener("click", () => transactionDialog(b.dataset.new)));
  $("#btn-import", el).addEventListener("click", () => csvImportDialog());
  const form = $("#tx-filters", el);
  let timer;
  form.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(applyFilters, 250); });
  form.addEventListener("change", applyFilters);
  form.addEventListener("reset", () => setTimeout(applyFilters));
  form.addEventListener("submit", (e) => e.preventDefault());
  $("#tx-more", el).addEventListener("click", () => load(true));
}

function applyFilters() {
  const f = formData($("#tx-filters", root));
  view.filters = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== ""));
  load(false).catch((e) => toast(e.message, true));
}

async function show() {
  await Promise.all([loadAccounts(), loadCategories()]);
  fillFilterSelects();
  // "#operazioni/conto/<id>" (Home cards) or "#operazioni/categoria/<id>/<from>/<to>" (Analytics)
  // open the list already filtered
  const m = /^#operazioni\/(conto|categoria)\/(\d+)(?:\/([\d-]{10})\/([\d-]{10}))?/.exec(location.hash);
  if (m) {
    const form = $("#tx-filters", root);
    form.reset();
    view.filters = {};
    const key = m[1] === "conto" ? "account" : "category";
    form.elements[key].value = m[2];
    view.filters[key] = m[2];
    if (m[3]) {
      form.elements.from.value = view.filters.from = m[3];
      form.elements.to.value = view.filters.to = m[4];
    }
    $("#filters-wrap", root).open = true;
    history.replaceState(null, "", "#operazioni");
  }
  await load(false);
}

function fillFilterSelects() {
  const form = $("#tx-filters", root);
  const acc = form.elements.account, cat = form.elements.category;
  const a = acc.value, c = cat.value;
  acc.innerHTML = `<option value="">Tutti</option>` + options(state.accounts, a, (x) => x.name + (x.archived ? " (archiviato)" : ""));
  const groups = [["expense", "Spese"], ["income", "Entrate"], ["transfer", "Trasferimenti"]];
  cat.innerHTML = `<option value="">Tutte</option>` + groups.map(([n, label]) =>
    `<optgroup label="${label}">${options(state.categories.filter((x) => x.nature === n), c)}</optgroup>`).join("");
}

async function load(more) {
  const params = new URLSearchParams({ ...view.filters, limit: PAGE, offset: more ? view.offset : 0 });
  const res = await api("GET", `/api/transactions?${params}`);
  view.items = more ? view.items.concat(res.items) : res.items;
  view.offset = view.items.length;
  view.hasMore = res.has_more;
  view.total = res.total;
  render();
}

function render() {
  const box = $("#tx-table", root);
  $("#tx-more", root).hidden = !view.hasMore;
  $("#tx-count", root).textContent = view.total ? `${view.items.length} di ${view.total} operazioni` : "";
  if (!view.items.length) {
    const any = Object.keys(view.filters).length;
    box.innerHTML = `<div class="empty-row">${any ? "Nessuna operazione con questi filtri." : "Nessuna operazione: aggiungi la prima con i pulsanti qui sopra."}</div>`;
    return;
  }
  box.innerHTML = `
    <table class="table tx-table">
      <thead><tr><th class="hide-sm">Data</th><th>Descrizione</th><th class="hide-sm">Conto</th><th class="num">Importo</th><th class="num hide-md">EUR</th><th class="actions"></th></tr></thead>
      <tbody>${view.items.map(row).join("")}</tbody>
    </table>`;
  $$("[data-act]", box).forEach((b) => b.addEventListener("click", () => act(b.dataset.act, Number(b.dataset.id))));
}

function signOf(t) {
  if (["expense", "fee", "buy"].includes(t.kind)) return -1;
  if (["income", "interest", "sell"].includes(t.kind)) return 1;
  return 0;
}

function row(t) {
  const sign = signOf(t);
  const cls = sign < 0 ? "neg" : sign > 0 ? "pos" : "";
  const prefix = sign < 0 ? "−" : sign > 0 ? "+" : "";
  const account = t.kind === "transfer"
    ? `${esc(t.from_account_name)} <span class="arrow">→</span> ${esc(t.to_account_name)}`
    : esc(t.account_name);
  let amount = `<span class="${cls}">${prefix}${money(t.amount, t.currency)}</span>`;
  if (t.kind === "transfer" && t.from_currency !== t.to_currency) {
    amount += `<div class="cell-sub">inviati ${money(t.from_amount, t.from_currency)}</div>`;
  }
  if (t.fee) amount += `<div class="cell-sub">comm. ${money(t.fee.amount, t.fee.currency)}</div>`;
  const eur = t.eur == null
    ? (t.currency === "EUR" ? "" : `<span class="muted" title="Tasso di cambio non ancora disponibile">n.d.</span>`)
    : t.currency === "EUR" ? "" : money(t.eur, "EUR");
  const tags = [
    `<span class="kind-tag ${t.kind}">${KIND_LABELS[t.kind]}</span>`,
    t.category_name ? `<span class="cat">${esc(t.category_name)}</span>` : "",
    t.auto ? '<span class="pill">automatica</span>' : "",
  ].join("");
  const actions = t.editable
    ? `<button class="icon-btn" title="Modifica" data-act="edit" data-id="${t.id}">${ICON.edit}</button>
       <button class="icon-btn danger" title="Elimina" data-act="delete" data-id="${t.id}">${ICON.trash}</button>`
    : `<span class="muted small" title="Si gestisce dalla scheda Investimenti">—</span>`;
  return `<tr>
    <td class="nowrap hide-sm">${dateFmt(t.date)}</td>
    <td><div class="cell-main">${esc(t.description) || `<span class="muted">${KIND_LABELS[t.kind]}</span>`}</div><div class="tags">${tags}</div>
      <div class="cell-sub show-sm">${dateFmt(t.date)} · ${account}</div></td>
    <td class="hide-sm">${account}</td>
    <td class="num">${amount}</td>
    <td class="num hide-md muted">${eur}</td>
    <td class="actions">${actions}</td>
  </tr>`;
}

async function act(what, id) {
  const t = view.items.find((x) => x.id === id);
  if (!t) return;
  try {
    if (what === "edit") return transactionDialog(t.kind, t);
    if (what === "delete") {
      const extra = t.fee ? " Verrà eliminata anche la commissione collegata." : "";
      if (!(await confirmDialog("Elimina operazione", `Eliminare “${esc(t.description || KIND_LABELS[t.kind])}” del ${dateFmt(t.date)}?${extra}`, { confirmLabel: "Elimina" }))) return;
      await api("DELETE", `/api/transactions/${id}`);
      toast("Operazione eliminata");
      await loadAccounts();
      changed("transactions");
    }
  } catch (e) {
    toast(e.message, true);
  }
}

// ------------------------------------------------------------------ dialog --
const TITLES = {
  expense: ["Nuova spesa", "Modifica spesa"],
  income: ["Nuova entrata", "Modifica entrata"],
  transfer: ["Nuovo trasferimento", "Modifica trasferimento"],
  interest: ["Interessi", "Modifica interessi"],
  fee: ["Commissione", "Modifica commissione"],
};

/** Add or edit an operation. Exported so other views (Home) can open it. */
export async function transactionDialog(kind, t = null, preset = {}) {
  if (!state.categories.length) await loadCategories();
  const accs = activeAccounts().concat(t ? state.accounts.filter((a) => a.archived && [t.from_account_id, t.to_account_id].includes(a.id)) : []);
  if (!accs.length) { toast("Crea prima un conto dalla Home.", true); return null; }
  const isTransfer = kind === "transfer";
  return openDialog({
    title: TITLES[kind][t ? 1 : 0],
    render(body) {
      body.innerHTML = isTransfer ? transferFields(accs, t) : simpleFields(kind, accs, t, preset);
      wire(body, kind, t);
    },
    async onSubmit(form) {
      const data = formData(form);
      if (isTransfer && !form.elements.fee_on.checked) data.fee_amount = "";
      delete data.fee_on;
      const saved = t
        ? await api("PUT", `/api/transactions/${t.id}`, data)
        : await api("POST", "/api/transactions", { kind, ...data });
      await loadAccounts();
      changed("transactions");
      toast(t ? "Operazione aggiornata" : "Operazione salvata");
      (saved.warnings || []).forEach((w) => toast(w, true));
      return saved;
    },
  });
}

function catOptions(nature, selected) {
  const list = state.categories.filter((c) => c.nature === nature && (!c.archived || c.id === Number(selected)));
  return options(list, selected);
}

function simpleFields(kind, accs, t, preset = {}) {
  const side = kind === "income" || kind === "interest" ? "to" : "from";
  const accId = t ? t[`${side}_account_id`] : (preset.account_id || (accs[0] && accs[0].id));
  const nature = kind === "income" || kind === "interest" ? "income" : "expense";
  return `
    <div class="grid2">
      <label class="field span2">${side === "from" ? "Conto di origine" : "Conto di destinazione"}
        <select name="account_id">${options(accs, accId, (a) => `${a.name} · ${a.currency}`)}</select></label>
      <label class="field">Importo
        <div class="input-unit"><input name="amount" inputmode="decimal" autocomplete="off" placeholder="0,00" value="${t ? inputNum(t.amount) : ""}"><span class="unit" data-unit="account_id"></span></div>
        <span class="eur-hint" data-eur="amount"></span></label>
      <label class="field">Data<input type="date" name="date" max="${todayISO()}" value="${t ? t.date : todayISO()}"></label>
      ${kind === "interest" ? "" : `<label class="field span2">Categoria<select name="category_id">${catOptions(nature, t ? t.category_id : preset.category_id || "")}</select></label>`}
      <label class="field span2">Descrizione<input name="description" maxlength="200" autocomplete="off" value="${esc(t ? t.description : preset.description)}"></label>
    </div>`;
}

function transferFields(accs, t) {
  const from = t ? t.from_account_id : accs[0].id;
  const to = t ? t.to_account_id : (accs[1] || accs[0]).id;
  const fee = t && t.fee;
  const transferCat = t ? t.category_id : (state.categories.find((c) => c.system_key === "transfer") || {}).id;
  return `
    <div class="grid2">
      <label class="field">Da<select name="from_account_id">${options(accs, from, (a) => `${a.name} · ${a.currency}`)}</select></label>
      <label class="field">A<select name="to_account_id">${options(accs, to, (a) => `${a.name} · ${a.currency}`)}</select></label>
      <label class="field">Importo ricevuto
        <div class="input-unit"><input name="amount" inputmode="decimal" autocomplete="off" placeholder="0,00" value="${t ? inputNum(t.to_amount) : ""}"><span class="unit" data-unit="to_account_id"></span></div>
        <span class="eur-hint" data-eur="amount"></span></label>
      <label class="field" data-sent>Importo inviato
        <div class="input-unit"><input name="sent_amount" inputmode="decimal" autocomplete="off" placeholder="0,00" value="${t ? inputNum(t.from_amount) : ""}"><span class="unit" data-unit="from_account_id"></span></div>
        <span class="eur-hint" data-eur="sent_amount"></span></label>
      <label class="field">Data<input type="date" name="date" max="${todayISO()}" value="${t ? t.date : todayISO()}"></label>
      <label class="field">Categoria<select name="category_id">${catOptions("transfer", transferCat)}</select></label>
      <label class="field span2">Descrizione<input name="description" maxlength="200" autocomplete="off" value="${esc(t?.description)}"></label>
      <label class="check span2 fee-toggle"><input type="checkbox" name="fee_on" ${fee ? "checked" : ""}> Commissione bancaria</label>
      <div class="span2 grid2 fee-box" ${fee ? "" : "hidden"}>
        <label class="field">Importo commissione
          <div class="input-unit"><input name="fee_amount" inputmode="decimal" autocomplete="off" placeholder="0,00" value="${fee ? inputNum(fee.amount) : ""}"><span class="unit" data-unit="fee"></span></div></label>
        <label class="field">Addebitata su<select name="fee_side">
          <option value="from" ${!fee || fee.side === "from" ? "selected" : ""}>Conto di origine</option>
          <option value="to" ${fee && fee.side === "to" ? "selected" : ""}>Conto di destinazione</option></select></label>
      </div>
    </div>`;
}

function wire(body, kind, t) {
  const f = (name) => body.querySelector(`[name="${name}"]`);
  const cur = (sel) => (accountById(f(sel)?.value) || {}).currency || "";
  const dateEl = f("date");

  const update = () => {
    $$("[data-unit]", body).forEach((u) => {
      const k = u.dataset.unit;
      u.textContent = k === "fee" ? cur(f("fee_side").value === "to" ? "to_account_id" : "from_account_id") : cur(k);
    });
    if (kind === "transfer") {
      const same = cur("from_account_id") === cur("to_account_id");
      $("[data-sent]", body).hidden = same;
      const auto = `Trasferimento da ${accountById(f("from_account_id").value)?.name} a ${accountById(f("to_account_id").value)?.name}`;
      const d = f("description");
      if (!d.value || d.dataset.auto === d.value) { d.value = auto; d.dataset.auto = auto; }
    }
    $$("[data-eur]", body).forEach((h) => {
      const name = h.dataset.eur;
      const sel = kind === "transfer" ? (name === "amount" ? "to_account_id" : "from_account_id") : "account_id";
      eurHint(h, parseNum(f(name).value), cur(sel), dateEl.value);
    });
  };

  if (kind === "transfer") {
    const d = f("description");
    if (t) d.dataset.auto = `Trasferimento da ${t.from_account_name} a ${t.to_account_name}`;
    f("fee_on").addEventListener("change", () => {
      body.querySelector(".fee-box").hidden = !f("fee_on").checked;
      if (f("fee_on").checked) f("fee_amount").focus();
    });
    // different currencies: prefill the sent amount with the market rate (editable)
    const prefill = () => {
      const src = cur("from_account_id"), dst = cur("to_account_id");
      if (src === dst || f("sent_amount").dataset.touched) return;
      const conv = convert(parseNum(f("amount").value), dst, src);
      if (conv != null) f("sent_amount").value = inputNum(conv.toFixed(2));
    };
    f("sent_amount").addEventListener("input", () => { f("sent_amount").dataset.touched = "1"; });
    if (t) f("sent_amount").dataset.touched = "1";
    ["amount", "from_account_id", "to_account_id", "date"].forEach((n) => f(n).addEventListener("input", prefill));
    ["from_account_id", "to_account_id"].forEach((n) => f(n).addEventListener("change", () => { delete f("sent_amount").dataset.touched; prefill(); }));
  }
  body.addEventListener("input", update);
  body.addEventListener("change", update);
  update();
}

/** Convert with the latest known rates (preview only); null if a rate is missing. */
function convert(value, fromCur, toCur) {
  if (!isFinite(value)) return null;
  const r = state.rates || {};
  const a = fromCur === "EUR" ? 1 : r[fromCur] && Number(r[fromCur].rate);
  const b = toCur === "EUR" ? 1 : r[toCur] && Number(r[toCur].rate);
  if (!a || !b) return null;
  return (value * a) / b;
}

export default { mount, show };
