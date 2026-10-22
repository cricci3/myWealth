/* Savings account yield: rate history, generated interest, recalculation. */
import { $, $$, api, changed, confirmDialog, dateFmt, esc, ICON, loadAccounts, money, monthName, num, openDialog, toast, todayISO } from "../core.js";

export function savingsDialog(account) {
  let data = null;
  return openDialog({
    title: `Rendimento · ${account.name}`,
    wide: true,
    cancelLabel: "Chiudi",
    render(body) {
      body.innerHTML = `<div data-box><div class="empty-row">Caricamento…</div></div>`;
      load();

      async function load() {
        try {
          data = await api("GET", `/api/savings/${account.id}`);
          draw();
        } catch (e) { toast(e.message, true); }
      }

      function draw() {
        const box = $("[data-box]", body);
        const rates = data.rates.slice().reverse();
        box.innerHTML = `
          <p class="dlg-note">Gli interessi maturano ogni giorno sul saldo di fine giornata (tasso annuo / 12 / giorni del mese)
            e vengono accreditati l'ultimo giorno del mese come operazione automatica, modificabile o eliminabile.</p>
          <div class="grid2 savings-grid">
            <div>
              <h3 class="sub-title">Tassi</h3>
              <div class="inline-form" data-add>
                <label class="field">Rendimento annuo %<input name="annual_rate" inputmode="decimal" placeholder="es. 2,5"></label>
                <label class="field">Valido dal<input type="date" name="valid_from" value="${todayISO()}" min="${account.opened_on}"></label>
                <button class="btn btn-sm" type="button" data-go>${ICON.plus}Aggiungi</button>
              </div>
              ${rates.length ? `<table class="table compact"><thead><tr><th>Dal</th><th class="num">Tasso</th><th class="actions"></th></tr></thead><tbody>
                ${rates.map((r) => `<tr><td>${dateFmt(r.valid_from)}</td><td class="num">${num(r.annual_rate, 4)}%</td>
                  <td class="actions"><button type="button" class="icon-btn danger" title="Elimina" data-del="${r.id}">${ICON.trash}</button></td></tr>`).join("")}
              </tbody></table>` : `<div class="empty-row">Nessun tasso: il conto non matura interessi.</div>`}
            </div>
            <div>
              <h3 class="sub-title">Interessi generati</h3>
              ${data.months.length ? `<table class="table compact"><thead><tr><th>Mese</th><th class="num">Lordo</th><th class="num">Ritenuta</th><th class="num">Accreditato</th></tr></thead><tbody>
                ${data.months.map((m) => `<tr><td>${monthName(m.month)}</td><td class="num">${money(m.gross, account.currency)}</td>
                  <td class="num muted">${Number(m.tax) ? money(m.tax, account.currency) : "—"}</td>
                  <td class="num">${m.credited != null ? money(m.credited, account.currency) : `<span class="muted">${Number(m.gross) ? "eliminato" : "—"}</span>`}</td></tr>`).join("")}
              </tbody></table>` : `<div class="empty-row">Nessun mese concluso da calcolare.</div>`}
              <div class="inline-form" data-recalc>
                <label class="field">Ricalcola dal mese<input type="month" name="from_month" max="${todayISO().slice(0, 7)}" value="${data.months.length ? data.months[data.months.length - 1].month : todayISO().slice(0, 7)}"></label>
                <button class="btn btn-sm" type="button" data-go>${ICON.refresh}Ricalcola</button>
              </div>
            </div>
          </div>`;
        $$(".inline-form input", box).forEach((i) => i.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); $("[data-go]", i.closest(".inline-form")).click(); }
        }));
        const add = $("[data-add]", box);
        $("[data-go]", add).addEventListener("click", async () => {
          const val = (n) => $(`[name="${n}"]`, add).value;
          try {
            const res = await api("POST", `/api/savings/${account.id}/rates`, { annual_rate: val("annual_rate"), valid_from: val("valid_from") });
            toast(res.generated.length ? `Tasso salvato · interessi generati per ${res.generated.length} mes${res.generated.length === 1 ? "e" : "i"}` : "Tasso salvato");
            await afterChange();
          } catch (e) { toast(e.message, true); }
        });
        $$("[data-del]", box).forEach((b) => b.addEventListener("click", async () => {
          try {
            await api("DELETE", `/api/savings/${account.id}/rates/${b.dataset.del}`);
            toast("Tasso eliminato: gli interessi già generati restano (usa Ricalcola).");
            await afterChange();
          } catch (e) { toast(e.message, true); }
        }));
        const recalc = $("[data-recalc]", box);
        $("[data-go]", recalc).addEventListener("click", async () => {
          const month = $('[name="from_month"]', recalc).value;
          if (!month) return;
          const ok = await confirmDialog("Ricalcola interessi",
            `Gli interessi generati da ${esc(monthName(month))} in poi verranno eliminati e calcolati di nuovo. Le modifiche fatte a mano su quelle operazioni andranno perse.`,
            { confirmLabel: "Ricalcola" });
          if (!ok) return;
          try {
            const res = await api("POST", `/api/savings/${account.id}/recalculate`, { from_month: month });
            toast(`Interessi ricalcolati: ${res.generated.length} mes${res.generated.length === 1 ? "e" : "i"}`);
            await afterChange();
          } catch (e) { toast(e.message, true); }
        });
      }

      async function afterChange() {
        await loadAccounts();
        changed("savings");
        await load();
      }
    },
  });
}
