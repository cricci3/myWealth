/* Import of the encrypted files sent from the smartphone (SPEC §16.6): from the inbox folder
 * (badge in the sidebar) or chosen/dropped by hand. Files are decrypted here, merged into
 * one CSV and sent to the usual import preview; rows already imported (same id) are skipped. */
import { $, api, changed, esc, loadAccounts, loadCategories, openDialog, toast } from "./core.js";
import { previewHtml } from "./csvimport.js";
import { decryptFile, importKey } from "./mobilefile.js";

const CHECK_EVERY = 2 * 60 * 1000;

// ------------------------------------------------------------------ badge --
/** Look for files in the inbox folder and show/hide the sidebar badge. */
export async function checkInbox() {
  const badge = $("#mobile-badge");
  if (!badge) return;
  let res;
  try { res = await api("GET", "/api/mobile/inbox"); } catch (e) { return; }
  const n = res.files.length;
  badge.hidden = n === 0;
  $("#mobile-badge-count").textContent = String(n);
  const text = `${n} file da smartphone`;
  $("#mobile-badge-label").textContent = text;
  badge.title = `${text}: importa`;
}

export function watchInbox() {
  checkInbox();
  setInterval(checkInbox, CHECK_EVERY);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkInbox(); });
  $("#mobile-badge").addEventListener("click", () => mobileImportDialog({ inbox: true }));
  // Files dropped anywhere in the window (outside an open dialog) start an import.
  window.addEventListener("dragover", (ev) => { if (hasFiles(ev)) ev.preventDefault(); });
  window.addEventListener("drop", (ev) => {
    if (!hasFiles(ev) || document.querySelector("dialog[open]")) return;
    ev.preventDefault();
    const files = [...ev.dataTransfer.files].filter((f) => /\.txt$/i.test(f.name));
    if (files.length) mobileImportDialog({ files });
    else toast("Trascina qui i file .txt esportati dallo smartphone.", true);
  });
}

const hasFiles = (ev) => [...(ev.dataTransfer?.types || [])].includes("Files");

// ----------------------------------------------------------------- dialog --
/** Merge the decrypted CSVs (same header) and remember which file each line comes from. */
function merge(sources) {
  const ok = sources.filter((s) => s.csv);
  if (!ok.length) return null;
  const lines = (csv) => csv.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
  const header = lines(ok[0].csv)[0];
  const out = [header];
  const origin = [null, null]; // CSV line number (1 = header) -> [file, line in that file]
  for (const s of ok) {
    const [h, ...rows] = lines(s.csv);
    if (h !== header) { s.error = "Formato diverso dagli altri file: importalo da solo."; s.csv = null; continue; }
    rows.forEach((r, i) => { out.push(r); origin.push([s.name, i + 2]); });
  }
  return { text: out.join("\r\n") + "\r\n", origin };
}

export async function mobileImportDialog({ inbox = false, files = [] } = {}) {
  let key;
  try {
    const k = await api("GET", "/api/mobile/key");
    key = { kid: k.kid, cryptoKey: await importKey(k.key) };
  } catch (e) {
    toast(e.message, true);
    return null;
  }
  await Promise.all([loadAccounts(), loadCategories()]);
  const sources = []; // {name, text, inInbox, csv, error, rows}
  let merged = null;
  let preview = null;
  let seq = 0;

  return openDialog({
    title: "Importa da smartphone",
    wide: true,
    submitLabel: "Importa",
    render(body, { dialog }) {
      body.innerHTML = `
        <p class="dlg-note">File esportati dall'app myWealth sul telefono (<span class="mono">mywealth-….txt</span>), decifrati qui con la chiave dell'abbinamento.
          Le voci già importate vengono saltate; il resto viene importato tutto insieme, oppure niente.</p>
        <div class="drop-zone" data-drop>
          <span>Trascina qui i file, oppure</span>
          <label class="btn btn-sm">Scegli file<input type="file" accept=".txt,text/plain" multiple data-file hidden></label>
        </div>
        <ul class="file-list" data-files></ul>
        <label class="check"><input type="checkbox" data-create> Crea le categorie mancanti</label>
        <div data-result></div>`;
      const submit = $('button[type="submit"]', dialog);
      submit.disabled = true;
      const zone = $("[data-drop]", body);

      const renderFiles = () => {
        $("[data-files]", body).innerHTML = sources.map((s) => `<li>
          <span class="mono">${esc(s.name)}</span>${s.inInbox ? ' <span class="muted small">cartella in arrivo</span>' : ""}
          ${s.error ? `<span class="neg">${esc(s.error)}</span>` : s.csv ? `<span class="pos">${s.rows} voc${s.rows === 1 ? "e" : "i"}</span>` : '<span class="muted">…</span>'}
        </li>`).join("");
      };

      const run = async () => {
        renderFiles();
        merged = merge(sources);
        renderFiles();
        const box = $("[data-result]", body);
        const my = ++seq;
        preview = null;
        submit.disabled = true;
        if (!merged) { box.innerHTML = ""; return; }
        try {
          const r = await api("POST", `/api/mobile/preview?create_categories=${$("[data-create]", body).checked ? 1 : 0}`, new Blob([merged.text]));
          if (my !== seq) return;
          preview = r;
          const label = (line) => { const o = merged.origin[line]; return o ? (sources.length > 1 ? `${o[0].replace(/^mywealth-|\.txt$/gi, "")} · ${o[1]}` : String(o[1])) : String(line); };
          const stale = r.rows.some((x) => x.errors.some((m) => /inesistente|sconosciuta/.test(m)));
          box.innerHTML = previewHtml(r, label) + (stale ? `<p class="dlg-note warn-text">Conti o categorie cambiati sul PC dopo l'ultimo abbinamento? Aggiorna la configurazione sul telefono: Impostazioni → Smartphone → Mostra QR configurazione.</p>` : "");
          submit.disabled = r.errors > 0 || (r.valid === 0 && r.skipped === 0);
          submit.textContent = r.valid ? `Importa ${r.valid} operazion${r.valid === 1 ? "e" : "i"}` : "Rimuovi i file già importati";
          if (!r.valid && !sources.some((s) => s.inInbox && s.csv)) submit.disabled = true;
        } catch (e) {
          if (my !== seq) return;
          box.innerHTML = `<div class="dlg-error">${esc(e.message)}</div>`;
        }
      };

      const add = async (list) => {
        for (const item of list) {
          if (sources.some((s) => s.name === item.name && s.text === item.text)) continue;
          const s = { ...item, csv: null, error: null, rows: 0 };
          sources.push(s);
          try {
            s.csv = (await decryptFile(s.text, key.cryptoKey, key.kid)).csv;
            s.rows = Math.max(0, s.csv.split(/\r?\n/).filter((l) => l.trim()).length - 1);
          } catch (e) { s.error = e.message; }
        }
        await run();
      };

      const inboxFiles = async () => {
        try {
          const res = await api("GET", "/api/mobile/inbox");
          return Promise.all(res.files.map(async (f) => ({ ...(await api("GET", `/api/mobile/inbox/file?name=${encodeURIComponent(f.name)}`)), inInbox: true })));
        } catch (e) { return []; }
      };

      // Picked files that are also in the inbox folder (same name and content) are deleted after the import.
      const addPicked = async (picked) => {
        const inboxed = await inboxFiles();
        const list = await Promise.all([...picked].map(async (f) => {
          const text = await f.text();
          const twin = inboxed.find((x) => x.name === f.name && x.content === text);
          return { name: f.name, text, inInbox: Boolean(twin) };
        }));
        await add(list);
      };

      $("[data-file]", body).addEventListener("change", (ev) => { addPicked(ev.target.files); ev.target.value = ""; });
      $("[data-create]", body).addEventListener("change", run);
      zone.addEventListener("dragover", (ev) => { ev.preventDefault(); zone.classList.add("over"); });
      zone.addEventListener("dragleave", () => zone.classList.remove("over"));
      dialog.addEventListener("dragover", (ev) => ev.preventDefault());
      dialog.addEventListener("drop", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        zone.classList.remove("over");
        addPicked([...ev.dataTransfer.files]);
      });

      (async () => {
        if (inbox) add((await inboxFiles()).map((f) => ({ name: f.name, text: f.content, inInbox: true })));
        if (files.length) addPicked(files);
      })();
    },
    async onSubmit() {
      if (!merged || !preview) throw new Error("Scegli i file da importare.");
      const names = sources.filter((s) => s.inInbox && s.csv).map((s) => s.name);
      const create = document.querySelector("dialog [data-create]").checked ? 1 : 0;
      const res = await api("POST", `/api/mobile/import?create_categories=${create}&files=${encodeURIComponent(names.join("/"))}`, new Blob([merged.text]));
      await Promise.all([loadAccounts(), loadCategories()]);
      changed("import");
      checkInbox();
      const manual = sources.filter((s) => s.csv && !s.inInbox).length;
      toast(`${res.imported} operazion${res.imported === 1 ? "e importata" : "i importate"}`
        + (res.skipped ? `, ${res.skipped} già presenti` : "")
        + (manual ? ". Ora puoi eliminare i file scelti a mano." : ""));
      return res;
    },
  });
}
