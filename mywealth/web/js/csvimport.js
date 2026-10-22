/* CSV imports: the app's own format, and bank statements through a column mapping. */
import {
  $, $$, activeAccounts, api, changed, dateFmt, download, esc, loadAccounts, loadCategories, openDialog, options, state,
  toast,
} from "./core.js";

const KINDS = { expense: "Spesa", income: "Entrata", transfer: "Trasferimento" };

/** Preview table of an import; `lineLabel` turns a CSV line number into the text shown. */
export function previewHtml(r, lineLabel = (line) => line) {
  const newCats = r.new_categories.length
    ? `<p class="small">Categorie non trovate: ${r.new_categories.map((c) => `<b>${esc(c.name)}</b>`).join(", ")} — spunta “Crea le categorie mancanti” per aggiungerle.</p>` : "";
  const outcome = (x) => (x.errors.length ? `<span class="neg">${esc(x.errors.join("; "))}</span>`
    : x.skipped ? `<span class="muted">${esc(x.skipped)}</span>`
    : x.warnings.length ? `<span class="warn-text">${esc(x.warnings.join("; "))}</span>` : '<span class="pos">ok</span>');
  return `
    <div class="import-summary">
      <span><b>${r.total}</b> righe</span><span class="pos"><b>${r.valid}</b> valide</span>
      <span class="${r.errors ? "neg" : "muted"}"><b>${r.errors}</b> con errori</span>
      <span class="${r.duplicates ? "warn-text" : "muted"}"><b>${r.duplicates}</b> possibili duplicati</span>
      ${r.skipped !== undefined ? `<span class="muted"><b>${r.skipped}</b> già importate</span>` : ""}
    </div>
    ${newCats}
    <div class="table-card preview-table"><div><table class="table compact">
      <thead><tr><th>Riga</th><th>Data</th><th>Tipo</th><th>Conto</th><th class="num">Importo</th><th>Categoria</th><th>Descrizione</th><th>Esito</th></tr></thead>
      <tbody>${r.rows.map((x) => `<tr class="${x.errors.length ? "row-error" : x.skipped ? "row-skipped" : x.warnings.length ? "row-warn" : ""}">
        <td class="nowrap">${esc(lineLabel(x.line))}</td><td class="nowrap">${x.date ? dateFmt(x.date) : "—"}</td><td>${KINDS[x.kind] || "—"}</td>
        <td>${esc(x.account || "")}${x.to_account ? ` → ${esc(x.to_account)}` : ""}</td><td class="num">${esc(x.amount)}</td>
        <td>${esc(x.category)}</td><td>${esc(x.description)}</td>
        <td>${outcome(x)}</td></tr>`).join("")}
      </tbody></table></div></div>`;
}

/**
 * Shared flow: `previewUrl()`/`importUrl()` return the endpoints (with query) or null when
 * the input isn't complete yet; the file is sent as raw bytes.
 */
function importFlow(body, dialog, getData, previewUrl) {
  const submit = $('button[type="submit"]', dialog);
  submit.disabled = true;
  let seq = 0;
  return async function run() {
    const data = getData();
    const url = previewUrl();
    const box = $("[data-result]", body);
    if (!data || !url) { box.innerHTML = ""; submit.disabled = true; return; }
    const my = ++seq;
    let r;
    try {
      r = await api("POST", url, data);
    } catch (e) {
      if (my !== seq) return;
      box.innerHTML = `<div class="dlg-error">${esc(e.message)}</div>`;
      submit.disabled = true;
      return;
    }
    if (my !== seq) return;
    box.innerHTML = previewHtml(r);
    submit.disabled = r.errors > 0 || r.valid === 0;
    submit.textContent = r.valid ? `Importa ${r.valid} operazion${r.valid === 1 ? "e" : "i"}` : "Importa";
  };
}

async function finish(res) {
  await Promise.all([loadAccounts(), loadCategories()]);
  changed("import");
  toast(`${res.imported} operazioni importate`);
  return res;
}

export function csvImportDialog() {
  let data = null;
  const create = () => (document.querySelector("dialog [data-create]").checked ? "1" : "0");
  return openDialog({
    title: "Importa operazioni da CSV",
    wide: true,
    submitLabel: "Importa",
    render(body, { dialog }) {
      body.innerHTML = `
        <p class="dlg-note">Formato: <span class="mono">data;tipo;conto_origine;conto_destinazione;importo;importo_destinazione;categoria;descrizione</span>.
          Separatore “;” o “,”, decimali con virgola o punto, date gg/mm/aaaa o aaaa-mm-gg. Le righe vengono importate tutte insieme, oppure nessuna.
          <button type="button" class="link" data-template>Scarica il modello</button></p>
        <div class="row-actions">
          <input type="file" accept=".csv,text/csv" data-file class="file-input">
          <label class="check"><input type="checkbox" data-create> Crea le categorie mancanti</label>
        </div>
        <div data-result></div>`;
      $("[data-template]", body).addEventListener("click", () => download("/api/import/template", "modello.csv").catch((e) => toast(e.message, true)));
      const run = importFlow(body, dialog, () => data, () => `/api/import/preview?create_categories=${create()}`);
      $("[data-file]", body).addEventListener("change", async (ev) => {
        const f = ev.target.files[0];
        if (!f) return;
        data = await f.arrayBuffer();
        run();
      });
      $("[data-create]", body).addEventListener("change", run);
    },
    async onSubmit() {
      if (!data) throw new Error("Scegli un file CSV.");
      return finish(await api("POST", `/api/import/csv?create_categories=${create()}`, data));
    },
  });
}

// --------------------------------------------------------- bank statements --
const FIELDS = [
  ["date_col", "Data", true], ["description_col", "Descrizione", false], ["amount_col", "Importo (con segno)", false],
  ["debit_col", "Uscite", false], ["credit_col", "Entrate", false],
];

export async function bankImportDialog() {
  await Promise.all([loadAccounts(), loadCategories()]);
  let mappings = await api("GET", "/api/import/bank/mappings");
  let data = null;
  let header = [];
  let query = null;
  const accs = activeAccounts().filter((a) => a.behavior !== "investment");
  if (!accs.length) { toast("Crea prima un conto.", true); return null; }
  return openDialog({
    title: "Importa estratto conto della banca",
    wide: true,
    submitLabel: "Importa",
    render(body, { dialog }) {
      const catOpts = (nature) => options(state.categories.filter((c) => c.nature === nature && !c.archived), "Altro", (c) => c.name, (c) => c.name);
      body.innerHTML = `
        <p class="dlg-note">Scegli il CSV esportato dall'home banking e indica quali colonne contengono data, importo e descrizione.
          Salva la mappatura con il nome della banca per riusarla la prossima volta. Le uscite diventano spese, le entrate entrate: le categorie si possono correggere dopo.</p>
        <div class="grid2">
          <label class="field">File<input type="file" accept=".csv,.txt,text/csv" data-file class="file-input"></label>
          <label class="field">Mappatura salvata<select data-saved><option value="">—</option>${mappings.map((m) => `<option>${esc(m.name)}</option>`).join("")}</select></label>
          <label class="field">Conto<select data-account>${options(accs, accs[0].id)}</select></label>
          <label class="field">Righe da saltare prima dell'intestazione<input type="number" min="0" max="50" value="0" data-skip></label>
        </div>
        <div class="mapping" data-mapping hidden>
          <div class="grid3">${FIELDS.map(([k, label]) => `<label class="field">${label}<select data-col="${k}"></select></label>`).join("")}
            <label class="field">Formato data<select data-datefmt><option value="dmy">gg/mm/aaaa</option><option value="ymd">aaaa-mm-gg</option><option value="mdy">mm/gg/aaaa</option></select></label>
            <label class="field">Categoria uscite<select data-expcat>${catOpts("expense")}</select></label>
            <label class="field">Categoria entrate<select data-inccat>${catOpts("income")}</select></label>
          </div>
          <div class="row-actions">
            <label class="check"><input type="checkbox" data-invert> Inverti il segno degli importi</label>
            <label class="check"><input type="checkbox" data-create> Crea le categorie mancanti</label>
            <span class="spacer"></span>
            <input class="input auto-w" data-name placeholder="Nome banca" maxlength="60">
            <button type="button" class="btn btn-sm" data-save>Salva mappatura</button>
          </div>
          <div class="table-card sample-table"><div data-sample></div></div>
        </div>
        <div data-result></div>`;
      const q = (sel) => $(sel, body);
      const mapping = () => {
        const m = { skip_rows: Number(q("[data-skip]").value || 0), date_format: q("[data-datefmt]").value, invert: q("[data-invert]").checked };
        for (const [k] of FIELDS) { const v = q(`[data-col="${k}"]`).value; m[k] = v === "" ? null : Number(v); }
        return m;
      };
      const buildQuery = () => {
        const m = mapping();
        if (m.date_col == null || (m.amount_col == null && m.debit_col == null && m.credit_col == null)) return null;
        return new URLSearchParams({
          mapping: JSON.stringify(m), account: q("[data-account]").value,
          expense_category: q("[data-expcat]").value, income_category: q("[data-inccat]").value,
          create_categories: q("[data-create]").checked ? "1" : "0",
        }).toString();
      };
      const run = importFlow(body, dialog, () => data, () => { query = buildQuery(); return query && `/api/import/bank/preview?${query}`; });
      const fillColumns = (preset) => {
        $$("[data-col]", body).forEach((sel) => {
          const k = sel.dataset.col, req = FIELDS.find((f) => f[0] === k)[2];
          const current = preset ? preset[k] : sel.value;
          sel.innerHTML = (req ? "" : `<option value="">—</option>`) + header.map((h, i) => `<option value="${i}">${esc(h || `Colonna ${i + 1}`)}</option>`).join("");
          const valid = current !== null && current !== undefined && current !== "" && Number(current) < header.length;
          sel.value = valid ? String(current) : req ? "0" : "";
        });
      };
      const loadSample = async (preset) => {
        if (!data) return;
        try {
          const s = await api("POST", `/api/import/bank/sample?skip_rows=${q("[data-skip]").value || 0}`, data);
          header = s.header;
          q("[data-mapping]").hidden = false;
          q("[data-sample]").innerHTML = `<table class="table compact"><thead><tr>${s.header.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
            <tbody>${s.rows.slice(0, 4).map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
          fillColumns(preset);
          run();
        } catch (e) { toast(e.message, true); }
      };
      q("[data-file]").addEventListener("change", async (ev) => {
        const f = ev.target.files[0];
        if (!f) return;
        data = await f.arrayBuffer();
        loadSample();
      });
      q("[data-skip]").addEventListener("change", () => loadSample());
      q("[data-saved]").addEventListener("change", (ev) => {
        const m = mappings.find((x) => x.name === ev.target.value);
        if (!m) return;
        q("[data-skip]").value = m.skip_rows;
        q("[data-datefmt]").value = m.date_format;
        q("[data-invert]").checked = m.invert;
        q("[data-name]").value = m.name;
        loadSample(m);
      });
      $$("[data-col], [data-datefmt], [data-invert], [data-account], [data-expcat], [data-inccat], [data-create]", body)
        .forEach((el) => el.addEventListener("change", run));
      q("[data-save]").addEventListener("click", async () => {
        try {
          mappings = await api("POST", "/api/import/bank/mappings", { ...mapping(), name: q("[data-name]").value });
          q("[data-saved]").innerHTML = `<option value="">—</option>` + mappings.map((m) => `<option>${esc(m.name)}</option>`).join("");
          q("[data-saved]").value = q("[data-name]").value.trim();
          toast("Mappatura salvata");
        } catch (e) { toast(e.message, true); }
      });
    },
    async onSubmit() {
      if (!data || !query) throw new Error("Scegli il file e le colonne.");
      return finish(await api("POST", `/api/import/bank?${query}`, data));
    },
  });
}
