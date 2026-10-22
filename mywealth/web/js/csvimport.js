/* CSV import of operations: file, preview with per-row errors, confirmation. */
import { $, api, changed, dateFmt, download, esc, loadAccounts, loadCategories, openDialog, toast } from "./core.js";

const KINDS = { expense: "Spesa", income: "Entrata", transfer: "Trasferimento" };

export function csvImportDialog() {
  let data = null;
  let last = null;
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
      const submit = $('button[type="submit"]', dialog);
      submit.disabled = true;
      $("[data-template]", body).addEventListener("click", () => download("/api/import/template", "modello.csv").catch((e) => toast(e.message, true)));
      const run = async () => {
        if (!data) return;
        const create = $("[data-create]", body).checked ? "1" : "0";
        try {
          last = await api("POST", `/api/import/preview?create_categories=${create}`, data);
        } catch (e) {
          $("[data-result]", body).innerHTML = `<div class="dlg-error">${esc(e.message)}</div>`;
          submit.disabled = true;
          return;
        }
        render(last);
        submit.disabled = last.errors > 0 || last.valid === 0;
        submit.textContent = last.valid ? `Importa ${last.valid} operazion${last.valid === 1 ? "e" : "i"}` : "Importa";
      };
      const render = (r) => {
        const newCats = r.new_categories.length
          ? `<p class="small">Categorie non trovate: ${r.new_categories.map((c) => `<b>${esc(c.name)}</b>`).join(", ")} — spunta “Crea le categorie mancanti” per aggiungerle.</p>` : "";
        $("[data-result]", body).innerHTML = `
          <div class="import-summary">
            <span><b>${r.total}</b> righe</span><span class="pos"><b>${r.valid}</b> valide</span>
            <span class="${r.errors ? "neg" : "muted"}"><b>${r.errors}</b> con errori</span>
            <span class="${r.duplicates ? "warn-text" : "muted"}"><b>${r.duplicates}</b> possibili duplicati</span>
          </div>
          ${newCats}
          <div class="table-card preview-table"><div><table class="table compact">
            <thead><tr><th>Riga</th><th>Data</th><th>Tipo</th><th>Conto</th><th class="num">Importo</th><th>Categoria</th><th>Descrizione</th><th>Esito</th></tr></thead>
            <tbody>${r.rows.map((x) => `<tr class="${x.errors.length ? "row-error" : x.warnings.length ? "row-warn" : ""}">
              <td>${x.line}</td><td class="nowrap">${x.date ? dateFmt(x.date) : "—"}</td><td>${KINDS[x.kind] || "—"}</td>
              <td>${esc(x.account || "")}${x.to_account ? ` → ${esc(x.to_account)}` : ""}</td><td class="num">${esc(x.amount)}</td>
              <td>${esc(x.category)}</td><td>${esc(x.description)}</td>
              <td>${x.errors.length ? `<span class="neg">${esc(x.errors.join("; "))}</span>` : x.warnings.length ? `<span class="warn-text">${esc(x.warnings.join("; "))}</span>` : '<span class="pos">ok</span>'}</td></tr>`).join("")}
            </tbody></table></div></div>`;
      };
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
      const create = document.querySelector("dialog [data-create]").checked ? "1" : "0";
      const res = await api("POST", `/api/import/csv?create_categories=${create}`, data);
      await Promise.all([loadAccounts(), loadCategories()]);
      changed("import");
      toast(`${res.imported} operazioni importate`);
      return res;
    },
  });
}
