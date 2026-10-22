/* "Esporta tutto" / "Importa tutto" (.mywealth archives) and restore from backups. */
import { api, dateFmt, download, esc, openDialog, toast } from "./core.js";

export const ARCHIVE_WARNING = "L'archivio contiene <b>tutti</b> i tuoi dati finanziari in chiaro: conservalo su un supporto sicuro e cancellalo dopo l'uso.";

export async function exportAll() {
  await download("/api/archive", "myWealth.mywealth");
  toast("Archivio scaricato");
}

function pickFile(accept) {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.addEventListener("change", () => resolve(input.files[0] || null));
    input.click();
  });
}

const created = (iso) => (iso ? `${dateFmt(iso.slice(0, 10))} alle ${iso.slice(11, 16)}` : "—");

/** Choose a .mywealth file, show what it contains, then replace all the data with it. */
export async function importAll() {
  const file = await pickFile(".mywealth,application/zip");
  if (!file) return false;
  const data = await file.arrayBuffer();
  let info;
  try {
    info = await api("POST", "/api/archive/inspect", data);
  } catch (e) {
    toast(e.message, true);
    return false;
  }
  const a = info.archive;
  const ok = await openDialog({
    title: "Importa tutto",
    submitLabel: "Sostituisci i dati",
    danger: !info.current_empty,
    render(body) {
      body.innerHTML = `
        <dl class="info compact-info">
          <dt>File</dt><dd>${esc(file.name)}</dd>
          <dt>Creato il</dt><dd>${created(a.created_at)}</dd>
          <dt>Contenuto</dt><dd>${a.accounts} conti, ${a.transactions} operazioni${a.assets ? `, ${a.assets} asset` : ""}</dd>
          <dt>Versione app</dt><dd>${esc(a.app_version)} (schema v${a.schema_version})</dd>
        </dl>
        ${info.current_empty ? "" : `<p class="dlg-note warn-note">I dati attuali verranno <b>sostituiti</b> (nessuna unione). Prima viene salvato un backup automatico, ripristinabile dalle Impostazioni.</p>`}`;
    },
    onSubmit: () => true,
  });
  if (!ok) return false;
  try {
    const res = await api("POST", "/api/archive/restore", data);
    toast(`Dati importati (${res.restored.accounts} conti)`);
    setTimeout(() => location.reload(), 900);
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

export async function restoreBackup(b) {
  const ok = await openDialog({
    title: "Ripristina backup",
    submitLabel: "Ripristina",
    danger: true,
    render(body) {
      body.innerHTML = `<p class="dlg-text">Ripristinare il backup del ${created(b.created_at)}?</p>
        <p class="dlg-note warn-note">I dati attuali verranno sostituiti; prima viene salvato un nuovo backup.</p>`;
    },
    onSubmit: () => true,
  });
  if (!ok) return;
  try {
    await api("POST", `/api/backups/${encodeURIComponent(b.name)}/restore`);
    toast("Backup ripristinato");
    setTimeout(() => location.reload(), 900);
  } catch (e) {
    toast(e.message, true);
  }
}
