/* Export: CSV/JSON downloads and the "move to another PC" archive. */
import { $, $$, download, loadAccounts, options, state, toast, todayISO } from "../core.js";
import { ARCHIVE_WARNING, exportAll, importAll } from "../transfer.js";

const DATASETS = {
  operazioni: { label: "Operazioni", hint: "Tutte le operazioni del periodo, nel formato dell'import CSV (più valuta e controvalore EUR).", period: true, account: true },
  conti: { label: "Conti", hint: "Nome, banca, valuta, tipo, apertura, saldo iniziale e attuale." },
  investimenti: { label: "Report investimenti", hint: "Per ogni asset: quote, investito, valore, guadagno, realizzato, XIRR." },
  "report-mensile": { label: "Report mensile", hint: "Per mese e per conto: entrate, uscite, trasferimenti, investito, anche in EUR.", period: true },
  categorie: { label: "Categorie", hint: "Categorie con natura e numero di operazioni." },
};

let root;
const view = { what: "operazioni", format: "csv" };

function mount(el) {
  root = el;
  const year = todayISO().slice(0, 4);
  el.innerHTML = `
    <div class="card pad">
      <h2 class="card-title">Esporta i dati</h2>
      <div class="dataset-list" id="ex-datasets">${Object.entries(DATASETS).map(([k, d]) => `
        <button type="button" class="dataset" data-what="${k}"><b>${d.label}</b><span>${d.hint}</span></button>`).join("")}
      </div>
      <div class="export-options">
        <div class="segmented" id="ex-format"><button type="button" data-format="csv">CSV</button><button type="button" data-format="json">JSON</button></div>
        <label class="field" data-period>Dal<input type="date" class="input" id="ex-from" value="${year}-01-01"></label>
        <label class="field" data-period>Al<input type="date" class="input" id="ex-to" value="${todayISO()}"></label>
        <label class="field" data-account>Conto<select class="input" id="ex-account"></select></label>
        <button class="btn btn-primary" type="button" id="ex-go">Scarica</button>
      </div>
      <p class="muted small">Il file viene scaricato dal browser: scegli tu dove salvarlo. Nessun dato resta nella cartella del progetto. Il CSV usa “;” come separatore e la virgola per i decimali (Excel italiano).</p>
    </div>

    <div class="card pad gap-top transfer-card">
      <h2 class="card-title">Trasferisci su un altro PC</h2>
      <p class="muted">Un unico file <span class="mono">.mywealth</span> con tutti i dati, le impostazioni e la cache di prezzi e cambi. Sull'altro PC: <b>Importa tutto</b> (o la schermata di primo avvio).</p>
      <p class="dlg-note warn-note">${ARCHIVE_WARNING}</p>
      <div class="row-actions">
        <button class="btn btn-primary" type="button" id="ex-all">Esporta tutto</button>
        <button class="btn" type="button" id="im-all">Importa tutto</button>
      </div>
    </div>`;
  $$("[data-what]", el).forEach((b) => b.addEventListener("click", () => { view.what = b.dataset.what; sync(); }));
  $$("[data-format]", el).forEach((b) => b.addEventListener("click", () => { view.format = b.dataset.format; sync(); }));
  $("#ex-go", el).addEventListener("click", go);
  $("#ex-all", el).addEventListener("click", async (ev) => {
    ev.currentTarget.disabled = true;
    try { await exportAll(); } catch (e) { toast(e.message, true); } finally { ev.currentTarget.disabled = false; }
  });
  $("#im-all", el).addEventListener("click", () => importAll());
}

function sync() {
  const d = DATASETS[view.what];
  $$("[data-what]", root).forEach((b) => b.classList.toggle("on", b.dataset.what === view.what));
  $$("[data-format]", root).forEach((b) => b.classList.toggle("on", b.dataset.format === view.format));
  $$("[data-period]", root).forEach((x) => { x.hidden = !d.period; });
  $$("[data-account]", root).forEach((x) => { x.hidden = !d.account; });
}

async function show() {
  await loadAccounts();
  const sel = $("#ex-account", root);
  sel.innerHTML = `<option value="">Tutti</option>` + options(state.accounts, sel.value);
  sync();
}

async function go() {
  const d = DATASETS[view.what];
  const p = new URLSearchParams({ format: view.format });
  if (d.period) { p.set("from", $("#ex-from", root).value); p.set("to", $("#ex-to", root).value); }
  if (d.account && $("#ex-account", root).value) p.set("account", $("#ex-account", root).value);
  const btn = $("#ex-go", root);
  btn.disabled = true;
  try {
    await download(`/api/export/${view.what}?${p}`, `myWealth_${view.what}.${view.format}`);
    toast("File scaricato");
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

export default { mount, show };
