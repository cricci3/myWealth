/* Analytics: expenses by category, income vs expenses, savings rate, account report, net worth. */
import { $, $$, api, dateFmt, esc, loadAccounts, money, monthName, monthShort, options, pct, signedMoney, state, store, todayISO, toast, tone } from "../core.js";
import { colorVar, drawBars, drawChart, drawDonut, drawHBars } from "../charts.js";

let root;
const view = {
  catMode: store("mw-an-cat") || "month", catAnchor: todayISO(), catFrom: "", catTo: "", catAccount: "",
  year: "", repMonth: todayISO().slice(0, 7), repYear: false,
  data: {},
};

function mount(el) {
  root = el;
  el.innerHTML = `
    <div class="card chart-card">
      <div class="chart-head">
        <div><h2>Spese per categoria</h2><div class="muted small" id="cat-period"></div></div>
        <div class="row-actions">
          <select class="input auto-w" id="cat-account" aria-label="Conto"></select>
          <div class="segmented" id="cat-mode">
            <button type="button" data-mode="month">Mese</button><button type="button" data-mode="quarter">Trimestre</button>
            <button type="button" data-mode="year">Anno</button><button type="button" data-mode="custom">Periodo</button>
          </div>
          <div class="pager" id="cat-pager"><button type="button" class="icon-btn bordered" data-step="-1" aria-label="Precedente">‹</button><button type="button" class="icon-btn bordered" data-step="1" aria-label="Successivo">›</button></div>
        </div>
      </div>
      <div class="row-actions custom-range" id="cat-custom" hidden>
        <label class="field">Dal<input type="date" class="input" id="cat-from"></label>
        <label class="field">Al<input type="date" class="input" id="cat-to"></label>
      </div>
      <div class="cat-layout"><div class="donut-box" id="cat-donut"></div><div id="cat-bars"></div></div>
      <div class="muted small" id="cat-missing"></div>
    </div>

    <div class="card chart-card">
      <div class="chart-head">
        <div><h2>Entrate e uscite</h2><div class="muted small">In EUR al cambio di ogni operazione. Esclusi trasferimenti tra conti propri e acquisti/vendite di asset.</div></div>
        <select class="input auto-w" id="mon-year" aria-label="Periodo"></select>
      </div>
      <div class="totals-row" id="mon-totals"></div>
      <div class="chart" id="mon-chart"></div>
      <div class="legend-row"><span><i style="background:var(--chart-in)"></i>Entrate</span><span><i style="background:var(--chart-out)"></i>Uscite</span></div>
      <h3 class="sub-title gap-top">Tasso di risparmio</h3>
      <div class="chart short" id="rate-chart"></div>
      <div class="muted small">(entrate − uscite) / entrate, per mese</div>
    </div>

    <div class="card chart-card">
      <div class="chart-head">
        <div><h2>Report per conto</h2><div class="muted small">Nella valuta del conto, con il controvalore EUR. Investito = acquisti − vendite di asset.</div></div>
        <div class="row-actions">
          <input type="month" class="input auto-w" id="rep-month" max="${todayISO().slice(0, 7)}">
          <label class="check"><input type="checkbox" id="rep-year"> Anno intero</label>
        </div>
      </div>
      <div class="table-card gap-top"><div id="rep-table"></div></div>
    </div>

    <div class="card chart-card">
      <div class="chart-head"><div><h2>Patrimonio netto</h2><div class="muted small">Totale in EUR a fine mese</div></div></div>
      <div class="chart" id="nw-chart"></div>
    </div>`;

  $$("#cat-mode button", el).forEach((b) => b.addEventListener("click", () => {
    view.catMode = b.dataset.mode;
    store("mw-an-cat", view.catMode);
    view.catAnchor = todayISO();
    loadCategories();
  }));
  $$("#cat-pager button", el).forEach((b) => b.addEventListener("click", () => { shiftAnchor(Number(b.dataset.step)); loadCategories(); }));
  $("#cat-account", el).addEventListener("change", (e) => { view.catAccount = e.target.value; loadCategories(); });
  ["cat-from", "cat-to"].forEach((id) => $(`#${id}`, el).addEventListener("change", () => {
    view.catFrom = $("#cat-from", el).value; view.catTo = $("#cat-to", el).value; loadCategories();
  }));
  $("#mon-year", el).addEventListener("change", (e) => { view.year = e.target.value; loadMonthly(); });
  $("#rep-month", el).addEventListener("change", (e) => { view.repMonth = e.target.value || todayISO().slice(0, 7); loadReport(); });
  $("#rep-year", el).addEventListener("change", (e) => { view.repYear = e.target.checked; loadReport(); });
  window.addEventListener("resize", () => { if (!root.closest(".view").hidden) drawAll(); });
  window.addEventListener("mw-theme", () => { if (!root.closest(".view").hidden) drawAll(); });
}

async function show() {
  await loadAccounts();
  $("#cat-account", root).innerHTML = `<option value="">Tutti i conti</option>` + options(state.accounts, view.catAccount);
  const firstYear = Math.min(...state.accounts.map((a) => Number(a.opened_on.slice(0, 4))), new Date().getFullYear());
  const years = [];
  for (let y = new Date().getFullYear(); y >= firstYear; y--) years.push(y);
  $("#mon-year", root).innerHTML = `<option value="">Ultimi 12 mesi</option>` + years.map((y) => `<option value="${y}" ${String(y) === view.year ? "selected" : ""}>${y}</option>`).join("");
  $("#rep-month", root).value = view.repMonth;
  await Promise.all([loadCategories(), loadMonthly(), loadReport(), loadNetWorth()]).catch((e) => toast(e.message, true));
}

function drawAll() {
  drawCategories();
  drawMonthly();
  drawNetWorth();
}

// ------------------------------------------------------------- categories --
function catRange() {
  const d = new Date(view.catAnchor + "T12:00:00");
  const iso = (x) => { x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 10); };
  const y = d.getFullYear(), m = d.getMonth();
  if (view.catMode === "month") return [iso(new Date(y, m, 1, 12)), iso(new Date(y, m + 1, 0, 12))];
  if (view.catMode === "quarter") { const q = Math.floor(m / 3) * 3; return [iso(new Date(y, q, 1, 12)), iso(new Date(y, q + 3, 0, 12))]; }
  if (view.catMode === "year") return [`${y}-01-01`, `${y}-12-31`];
  return [view.catFrom || `${y}-01-01`, view.catTo || todayISO()];
}

function shiftAnchor(step) {
  const d = new Date(view.catAnchor + "T12:00:00");
  const months = { month: 1, quarter: 3, year: 12 }[view.catMode] || 0;
  d.setMonth(d.getMonth() + step * months, 1);
  const iso = d.toISOString().slice(0, 10);
  view.catAnchor = iso > todayISO() ? todayISO() : iso;
}

function periodLabel(from, to) {
  if (view.catMode === "month") return monthName(from.slice(0, 7));
  if (view.catMode === "quarter") return `${Math.floor(Number(from.slice(5, 7)) / 3) + 1}° trimestre ${from.slice(0, 4)}`;
  if (view.catMode === "year") return from.slice(0, 4);
  return `dal ${dateFmt(from)} al ${dateFmt(to)}`;
}

async function loadCategories() {
  const [from, to] = catRange();
  $$("#cat-mode button", root).forEach((b) => b.classList.toggle("on", b.dataset.mode === view.catMode));
  $("#cat-custom", root).hidden = view.catMode !== "custom";
  $("#cat-pager", root).hidden = view.catMode === "custom";
  $("#cat-from", root).value = from; $("#cat-to", root).value = to;
  $('#cat-pager [data-step="1"]', root).disabled = to >= todayISO();
  const params = new URLSearchParams({ from, to });
  if (view.catAccount) params.set("account", view.catAccount);
  try {
    view.data.cat = await api("GET", `/api/analytics/categories?${params}`);
  } catch (e) { toast(e.message, true); return; }
  $("#cat-period", root).textContent = `${periodLabel(from, to)} · totale ${money(view.data.cat.total, "EUR")}`;
  drawCategories();
}

function drawCategories() {
  const d = view.data.cat;
  if (!d) return;
  const items = d.items.map((x, i) => ({ key: x.category_id, label: x.name, value: Number(x.eur), color: colorVar(i) }));
  drawDonut($("#cat-donut", root), items, { centerLabel: "Spese" });
  drawHBars($("#cat-bars", root), items, {
    onClick: (id) => {
      const [from, to] = catRange();
      location.hash = `#operazioni/categoria/${id}/${from}/${to}`;
    },
  });
  $("#cat-missing", root).textContent = d.missing ? `${d.missing} operazion${d.missing === 1 ? "e esclusa" : "i escluse"}: tasso di cambio mancante.` : "";
}

// ---------------------------------------------------------------- monthly --
async function loadMonthly() {
  const params = view.year ? `year=${view.year}` : "months=12";
  view.data.monthly = await api("GET", `/api/analytics/monthly?${params}`);
  drawMonthly();
}

function drawMonthly() {
  const d = view.data.monthly;
  if (!d) return;
  const t = d.total;
  $("#mon-totals", root).innerHTML = `
    <div><span class="label">Entrate</span><b class="fig pos">${money(t.income, "EUR")}</b></div>
    <div><span class="label">Uscite</span><b class="fig neg">${money(t.expenses, "EUR")}</b></div>
    <div><span class="label">Risparmio</span><b class="fig ${tone(t.net)}">${signedMoney(t.net, "EUR")}</b></div>
    <div><span class="label">Tasso di risparmio</span><b class="fig ${tone(t.savings_rate)}">${pct(t.savings_rate)}</b></div>
    ${d.missing ? `<div class="muted small">${d.missing} operazioni senza cambio escluse</div>` : ""}`;
  const labels = d.months.map((m) => m.month);
  const fmt = (ym, long) => (long ? monthName(ym) : monthShort(ym));
  drawBars($("#mon-chart", root), {
    labels,
    series: [
      { name: "Entrate", color: "var(--chart-in)", values: d.months.map((m) => Number(m.income)) },
      { name: "Uscite", color: "var(--chart-out)", values: d.months.map((m) => Number(m.expenses)) },
    ],
  }, {
    formatLabel: fmt,
    extraTip: (i) => `<div class="r"><span>Risparmio</span><span class="${tone(d.months[i].net)}">${signedMoney(d.months[i].net, "EUR")}</span></div>`,
  });
  drawBars($("#rate-chart", root), {
    labels,
    series: [{ name: "Tasso di risparmio %", color: "var(--a2)", values: d.months.map((m) => (m.savings_rate == null ? null : Math.round(m.savings_rate * 10) / 10)) }],
  }, { formatLabel: fmt, valueFormat: (v) => pct(v) });
}

// ----------------------------------------------------------------- report --
async function loadReport() {
  const ym = view.repMonth;
  const y = Number(ym.slice(0, 4)), m = Number(ym.slice(5, 7));
  const from = view.repYear ? `${y}-01-01` : `${ym}-01`;
  const last = new Date(y, view.repYear ? 12 : m, 0).getDate();
  const to = view.repYear ? `${y}-12-31` : `${ym}-${String(last).padStart(2, "0")}`;
  const r = await api("GET", `/api/analytics/accounts?from=${from}&to=${to}`);
  const cell = (row, col, neg = false, extra = "") => {
    const v = row[col], e = row[`${col}_eur`];
    const n = Number(v);
    const cls = n === 0 ? "muted" : neg ? (n > 0 ? "neg" : "pos") : tone(n);
    return `<td class="num ${extra}"><span class="${cls}">${n === 0 ? "—" : money(v, row.currency)}</span>${row.currency !== "EUR" && n !== 0 ? `<div class="cell-sub">${e == null ? "EUR n.d." : money(e, "EUR")}</div>` : ""}</td>`;
  };
  $("#rep-table", root).innerHTML = !r.accounts.length ? `<div class="empty-row">Nessun conto.</div>` : `
    <table class="table">
      <thead><tr><th>Conto · ${view.repYear ? y : esc(monthName(ym))}</th><th class="num">Entrate</th><th class="num">Uscite</th><th class="num hide-sm">Trasferimenti</th><th class="num">Investito</th></tr></thead>
      <tbody>${r.accounts.map((a) => `<tr><td><div class="cell-main">${esc(a.name)}</div><div class="cell-sub">${a.currency}</div></td>
        ${cell(a, "income")}${cell(a, "expenses", true)}${cell(a, "transfers", false, "hide-sm")}${cell(a, "invested")}</tr>`).join("")}
      </tbody>
      <tfoot><tr><td>Totale in EUR</td><td class="num">${money(r.totals.income, "EUR")}</td><td class="num">${money(r.totals.expenses, "EUR")}</td>
        <td class="num hide-sm">${money(r.totals.transfers, "EUR")}</td><td class="num">${money(r.totals.invested, "EUR")}</td></tr></tfoot>
    </table>`;
}

// -------------------------------------------------------------- net worth --
async function loadNetWorth() {
  view.data.nw = await api("GET", "/api/analytics/networth");
  drawNetWorth();
}

function drawNetWorth() {
  const p = view.data.nw && view.data.nw.points;
  if (!p) return;
  drawChart($("#nw-chart", root), { dates: p.map((x) => x.date), value: p.map((x) => x.eur) },
    { axes: true, interactive: true, currency: "EUR", noInvested: true, labels: { value: "Patrimonio" } });
}

export default { mount, show };
