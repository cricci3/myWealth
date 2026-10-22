/* Investments: one sub-tab per investment account (UI ported from PortfolioTracker). */
import {
  $, $$, api, changed, confirmDialog, dateFmt, esc, formData, ICON, inputNum, loadAccounts, loadCategories, money,
  num, openDialog, parseNum, pct, qty, share, signedMoney, state, store, toast, todayISO, tone,
} from "../core.js";
import { colorVar, drawChart, sliceRange } from "../charts.js";
import { transactionDialog } from "./operations.js";

const RANGES = [["1M", 30], ["3M", 91], ["6M", 182], ["1A", 365], ["Max", 0]];
let root, actions;
const view = { accounts: [], current: null, data: null, range: Number(store("mw-inv-range") || 0), sort: store("mw-inv-sort") || "value" };

function mount(el) {
  root = el;
  el.innerHTML = `
    <div class="subtabs" id="inv-tabs" role="tablist"></div>
    <div id="inv-body"></div>`;
  window.addEventListener("resize", () => { if (!root.closest(".view").hidden && view.data) drawCharts(); });
  window.addEventListener("mw-theme", () => { if (view.data) drawCharts(); });
}

async function show(el, actionsEl) {
  actions = actionsEl;
  view.accounts = await api("GET", "/api/investments");
  const visible = view.accounts.filter((a) => !a.archived || a.asset_count);
  const saved = Number(store("mw-inv-tab"));
  if (!visible.find((a) => a.id === view.current)) view.current = (visible.find((a) => a.id === saved) || visible[0] || {}).id ?? null;
  renderTabs(visible);
  renderActions();
  if (view.current == null) {
    view.data = null;
    $("#inv-body", root).innerHTML = `<div class="card empty"><h2>Nessun conto investimenti</h2>
      <p>Crea dalla Home un conto di tipo “Investimenti”: qui avrai una sottoscheda per ognuno, con asset, rendimento e XIRR.</p></div>`;
    return;
  }
  await load();
}

function renderTabs(list) {
  const box = $("#inv-tabs", root);
  box.hidden = list.length < 2;
  box.innerHTML = list.map((a) => `<button type="button" role="tab" class="subtab ${a.id === view.current ? "on" : ""}" aria-selected="${a.id === view.current}" data-id="${a.id}">
    ${esc(a.name)} <span class="muted">${a.currency}</span></button>`).join("");
  $$("[data-id]", box).forEach((b) => b.addEventListener("click", async () => {
    view.current = Number(b.dataset.id);
    store("mw-inv-tab", String(view.current));
    $$("[data-id]", box).forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", String(x === b)); });
    await load().catch((e) => toast(e.message, true));
  }));
}

function renderActions() {
  if (!actions) return;
  actions.innerHTML = view.current == null ? "" : `
    <button class="icon-btn bordered" type="button" id="inv-refresh" title="Aggiorna prezzi e cambi">${ICON.refresh}</button>
    <button class="btn btn-ghost" type="button" id="inv-pt" title="Importa un portfolio.json di PortfolioTracker">${ICON.upload}PortfolioTracker</button>
    <button class="btn" type="button" id="inv-dividend">${ICON.plus}Dividendo</button>
    <button class="btn btn-primary" type="button" id="inv-add">${ICON.plus}Asset</button>`;
  if (view.current == null) return;
  $("#inv-add", actions).addEventListener("click", () => addAssetDialog());
  $("#inv-pt", actions).addEventListener("click", () => ptImportDialog());
  $("#inv-dividend", actions).addEventListener("click", async () => {
    await loadCategories();
    const cat = state.categories.find((c) => c.system_key === "dividends");
    transactionDialog("income", null, { account_id: view.current, category_id: cat && cat.id, description: "Dividendo" });
  });
  $("#inv-refresh", actions).addEventListener("click", async (ev) => {
    const btn = ev.currentTarget;
    btn.classList.add("spinning"); btn.disabled = true;
    try {
      const res = await api("POST", "/api/investments/refresh");
      const errs = Object.entries((res.last && res.last.result && res.last.result.errors) || {});
      toast(errs.length ? `Non aggiornato ${errs[0][0]}: ${errs[0][1]}` : "Prezzi e cambi aggiornati", errs.length > 0);
      changed("prices");
    } catch (e) { toast(e.message, true); } finally { btn.classList.remove("spinning"); btn.disabled = false; }
  });
}

async function load() {
  view.data = await api("GET", `/api/investments/${view.current}`);
  render();
}

const acctCur = () => view.data.account.currency;
const m = (v, dec) => money(v, acctCur(), dec);
const sm = (v, dec) => signedMoney(v, acctCur(), dec);
const shortName = (a) => (a.name && a.name !== a.ticker ? a.name.replace(/\s+(UCITS ETF|ETF|Inc\.?|S\.p\.A\.?|plc|N\.V\.|AG|SE|Corporation)\b.*$/i, "") : a.ticker);
const held = (days) => days >= 365 ? `${(days / 365).toLocaleString("it-IT", { maximumFractionDigits: 1 })} anni` : `${Math.max(days, 0)} giorni`;

function render() {
  const d = view.data;
  const s = d.summary;
  const body = $("#inv-body", root);
  body.innerHTML = `
    <div class="card kpis">
      <div class="kpi"><div class="label">Liquidità</div><div class="v fig">${m(s.liquidity)}</div><div class="s">disponibile per acquisti</div></div>
      <div class="kpi"><div class="label">Investito</div><div class="v fig">${m(s.invested)}</div><div class="s">${s.asset_count} asset${s.error_count ? ` · <span class="neg">${s.error_count} senza dati</span>` : ""}</div></div>
      <div class="kpi"><div class="label">Valore attuale</div><div class="v fig ${tone(s.gain)}">${m(s.value)}</div><div class="s">totale conto ${m(s.total)}</div></div>
      <div class="kpi"><div class="label">Guadagno</div><div class="v fig ${tone(s.gain)}">${sm(s.gain)}</div><div class="s"><b class="${tone(s.return_pct)}">${pct(s.return_pct, 2)}</b>${Number(s.realized) ? ` · realizzato ${sm(s.realized)}` : " sull'investito"}</div></div>
      <div class="kpi"><div class="label">Rendimento annuo</div><div class="v fig ${tone(s.annualized_pct)}">${pct(s.annualized_pct)}</div><div class="s">XIRR (money-weighted)</div></div>
      <div class="kpi"><div class="label">Ultimi 12 mesi</div><div class="v fig ${tone(s.yoy_pct)}">${pct(s.yoy_pct)}</div><div class="s">${s.yoy_gain == null ? "serve 1 anno di storico" : `<b class="${tone(s.yoy_gain)}">${sm(s.yoy_gain)}</b> netto versamenti`}</div></div>
    </div>
    <div class="card chart-card" id="inv-overview" ${d.series && d.series.dates.length > 1 ? "" : "hidden"}>
      <div class="chart-head">
        <div><h2>Andamento</h2><div class="muted small">Valore delle posizioni e capitale investito (tratteggiato), in ${acctCur()}</div></div>
        <div class="segmented" id="inv-range">${RANGES.map(([l, v]) => `<button type="button" data-range="${v}" class="${v === view.range ? "on" : ""}">${l}</button>`).join("")}</div>
      </div>
      <div class="chart" id="inv-chart"></div>
      <div class="series-toggles" id="inv-toggles"></div>
      <div class="alloc" id="inv-alloc"></div>
    </div>
    <div class="section-head" ${d.assets.length ? "" : "hidden"}>
      <h2 class="section-title">Asset</h2>
      <label class="sort">Ordina per <select id="inv-sort" class="input">
        <option value="value">Valore</option><option value="return">Rendimento</option><option value="yoy">12 mesi</option><option value="name">Nome</option>
      </select></label>
    </div>
    <div class="asset-grid" id="inv-grid"></div>`;
  $$("#inv-range button", body).forEach((b) => b.addEventListener("click", () => {
    view.range = Number(b.dataset.range);
    store("mw-inv-range", String(view.range));
    $$("#inv-range button", body).forEach((x) => x.classList.toggle("on", x === b));
    drawMain();
  }));
  const sort = $("#inv-sort", body);
  sort.value = view.sort;
  sort.addEventListener("change", () => { view.sort = sort.value; store("mw-inv-sort", view.sort); renderGrid(); });
  renderGrid();
  drawCharts();
}

function colors() {
  const ranked = view.data.assets.filter((a) => !a.error && Number(a.value) > 0).sort((a, b) => b.value - a.value);
  const map = {};
  ranked.forEach((a, i) => { map[a.id] = colorVar(i); });
  return { ranked, map };
}

function hidden() {
  try { return new Set(JSON.parse(store("mw-inv-hidden") || "[]")); } catch (e) { return new Set(); }
}

function drawCharts() {
  drawMain();
  drawSparks();
}

function drawMain() {
  const d = view.data;
  if (!d || !d.series || d.series.dates.length < 2) return;
  const { ranked, map } = colors();
  const series = sliceRange(d.series, view.range);
  const hide = hidden();
  const perAsset = ranked.length >= 2;
  const byId = Object.fromEntries((series.assets || []).map((x) => [x.id, x]));
  const overlays = !perAsset ? [] : ranked.filter((a) => byId[a.id] && !hide.has(a.id))
    .map((a) => ({ label: shortName(a), color: map[a.id], value: byId[a.id].value, invested: byId[a.id].invested }));
  const row = $("#inv-toggles", root);
  row.hidden = !perAsset;
  if (perAsset) {
    const chip = (id, label, color) => `<button type="button" class="series-chip" data-id="${esc(id)}" aria-pressed="${!hide.has(String(id))}"><i style="background:${color}"></i>${esc(label)}</button>`;
    row.innerHTML = chip("total", "Totale", "var(--chart-total)") + ranked.map((a) => chip(a.id, shortName(a), map[a.id])).join("");
    $$(".series-chip", row).forEach((c) => c.addEventListener("click", () => {
      const h = hidden();
      const id = c.dataset.id === "total" ? "total" : Number(c.dataset.id);
      if (h.has(id)) h.delete(id); else h.add(id);
      store("mw-inv-hidden", JSON.stringify([...h]));
      drawMain();
    }));
  }
  drawChart($("#inv-chart", root), series, {
    axes: true, interactive: true, currency: acctCur(), overlays,
    hideTotal: perAsset && hide.has("total"), color: perAsset ? "var(--chart-total)" : undefined,
  });
  const alloc = $("#inv-alloc", root);
  const total = ranked.reduce((s, a) => s + Number(a.value), 0);
  alloc.hidden = ranked.length < 2;
  if (ranked.length >= 2) {
    alloc.innerHTML = `
      <div class="alloc-bar">${ranked.map((a) => `<i style="width:${(a.value / total) * 100}%;background:${map[a.id]}" title="${esc(a.ticker)}"></i>`).join("")}</div>
      <div class="alloc-legend">${ranked.map((a) => `<span><i style="background:${map[a.id]}"></i>${esc(shortName(a))} <b>${share((a.value / total) * 100)}</b></span>`).join("")}</div>`;
  }
}

function sortedAssets() {
  const key = {
    value: (a) => -(Number(a.value) || 0),
    return: (a) => -(a.return_pct ?? -1e9),
    yoy: (a) => -(a.yoy?.pct ?? -1e9),
    name: (a) => shortName(a).toLowerCase(),
  }[view.sort];
  return [...view.data.assets].sort((a, b) => (a.closed - b.closed) || (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
}

function renderGrid() {
  const d = view.data;
  const grid = $("#inv-grid", root);
  if (!d.assets.length) {
    grid.innerHTML = `<div class="card empty">
      <h2>Nessun asset</h2>
      <p>Aggiungi il primo investimento: cerca ticker, ISIN o nome, poi indica data e importo. L'importo viene preso dalla liquidità del conto (${m(d.summary.liquidity)}).</p>
      <button class="btn btn-primary" type="button" data-empty-add>${ICON.plus}Aggiungi asset</button></div>`;
    $("[data-empty-add]", grid).addEventListener("click", () => addAssetDialog());
    return;
  }
  grid.innerHTML = sortedAssets().map(assetCard).join("");
  $$("[data-act]", grid).forEach((b) => b.addEventListener("click", () => {
    const a = d.assets.find((x) => x.id === Number(b.closest("[data-asset]").dataset.asset));
    ({ buy: () => tradeDialog(a, "buy"), sell: () => tradeDialog(a, "sell"), detail: () => detailDialog(a), edit: () => editAssetDialog(a) })[b.dataset.act]();
  }));
  drawSparks();
}

function assetCard(a) {
  const letter = esc((shortName(a)[0] || "?").toUpperCase());
  const meta = [a.ticker, a.exchange, a.first_date ? "dal " + dateFmt(a.first_date) : ""].filter(Boolean).map(esc).join(" · ");
  const actionsHtml = (main) => `<div class="asset-actions">
    ${main}
    <button class="btn btn-sm btn-ghost" type="button" data-act="detail">Dettagli</button>
    <button class="icon-btn" type="button" data-act="edit" title="Modifica asset">${ICON.edit}</button></div>`;
  if (a.error) {
    return `<article class="card asset is-error" data-asset="${a.id}">
      <div class="asset-top"><div class="avatar">${letter}</div><div class="asset-name"><div class="n">${esc(shortName(a))}</div><div class="m">${meta}</div></div></div>
      <div class="err">${esc(a.error)}${a.price_error ? `<br><span class="muted">${esc(a.price_error)}</span>` : ""}</div>
      ${actionsHtml(`<button class="btn btn-sm" type="button" data-act="buy">${ICON.plus}Acquisto</button>`)}
    </article>`;
  }
  const n = a.trades.length;
  const yoy = a.yoy;
  return `<article class="card asset ${Number(a.gain) < 0 ? "is-neg" : ""} ${a.closed ? "is-closed" : ""}" data-asset="${a.id}">
    <div class="asset-top">
      <div class="avatar">${letter}</div>
      <div class="asset-name"><div class="n" title="${esc(a.name)}">${esc(shortName(a))}</div><div class="m">${meta}</div></div>
      ${a.closed ? '<span class="chip">chiuso</span>' : `<span class="chip ${tone(a.day_change_pct)}" title="Variazione dell'ultima seduta">${pct(a.day_change_pct, 2)} oggi</span>`}
    </div>
    <div class="asset-mid">
      <div>
        <div class="label">Valore</div>
        <div class="v fig">${m(a.value)}</div>
        <div class="d ${tone(a.gain)}">${a.closed ? `realizzato ${sm(a.realized)}` : `${pct(a.return_pct, 2)} · ${sm(a.gain)}`}</div>
      </div>
      <div class="spark" data-spark="${a.id}"></div>
    </div>
    <div class="asset-stats">
      <div><div class="label">Investito</div><div class="v">${m(a.invested)}</div><div class="s">${qty(a.shares, 4)} quote · ${n} op.</div></div>
      <div><div class="label">Annuo</div><div class="v ${tone(a.annualized_pct)}">${pct(a.annualized_pct)}</div><div class="s">${a.annualized_pct == null ? "dopo 6 mesi" : "XIRR"}</div></div>
      <div><div class="label">12 mesi</div><div class="v ${tone(yoy?.pct)}">${yoy ? pct(yoy.pct) : "—"}</div><div class="s ${yoy ? tone(yoy.gain) : ""}">${yoy ? sm(yoy.gain, 0) : held(a.held_days) + " di storico"}</div></div>
    </div>
    ${actionsHtml(`<button class="btn btn-sm" type="button" data-act="buy">${ICON.plus}Acquisto</button>
      ${a.closed ? "" : `<button class="btn btn-sm" type="button" data-act="sell">Vendi</button>`}`)}
  </article>`;
}

function drawSparks() {
  if (!view.data) return;
  for (const el of $$("[data-spark]", root)) {
    const a = view.data.assets.find((x) => x.id === Number(el.dataset.spark));
    if (a && a.series) drawChart(el, a.series, { color: Number(a.gain) >= 0 ? "var(--pos)" : "var(--neg)", currency: acctCur() });
  }
}

async function afterChange(msg) {
  toast(msg);
  await loadAccounts();
  changed("investments");
}

// ---------------------------------------------------------------- dialogs --

function tradeFields(kind, a, t = null) {
  const cur = acctCur();
  const sell = kind === "sell";
  return `
    <div class="grid2">
      <label class="field">Data<input type="date" name="date" max="${todayISO()}" value="${t ? t.date : todayISO()}"></label>
      <label class="field">${sell ? "Importo incassato" : "Importo investito"}
        <div class="input-unit"><input name="amount" inputmode="decimal" autocomplete="off" placeholder="0,00" value="${t ? inputNum(t.amount) : ""}"><span class="unit">${cur}</span></div>
        ${sell ? "" : `<span class="hint">Liquidità disponibile: ${m(view.data.summary.liquidity)}</span>`}</label>
      ${sell ? `
      <label class="field span2">Quote vendute
        <div class="row-actions"><input class="input grow" name="shares" inputmode="decimal" autocomplete="off" value="${t ? inputNum(t.shares_input) : ""}">
          ${a && !a.error ? `<button class="btn btn-sm" type="button" data-all>Tutte (${qty(a.shares, 6)})</button>` : ""}</div>
        <span class="hint">Il costo delle quote vendute (costo medio) esce dall'investito; la differenza con l'incasso è guadagno realizzato.</span></label>` : `
      <label class="field"><span>Prezzo unitario <span class="muted">(facoltativo)</span></span>
        <div class="input-unit"><input name="price" inputmode="decimal" autocomplete="off" value="${t ? inputNum(t.price_input) : ""}"><span class="unit">${esc(a ? a.currency : "")}</span></div>
        <span class="hint">Quello pagato al broker; altrimenti la chiusura del giorno.</span></label>
      <label class="field"><span>Quote <span class="muted">(facoltativo)</span></span>
        <input name="shares" inputmode="decimal" autocomplete="off" value="${t ? inputNum(t.shares_input) : ""}">
        <span class="hint">In alternativa al prezzo.</span></label>`}
      <label class="field"><span>Commissione <span class="muted">(facoltativa)</span></span>
        <div class="input-unit"><input name="fee" inputmode="decimal" autocomplete="off" placeholder="0,00" value="${t && t.fee ? inputNum(t.fee) : ""}"><span class="unit">${cur}</span></div>
        <span class="hint">Registrata come spesa “Commissioni bancarie”.</span></label>
      <label class="field">Nota<input name="note" maxlength="200" autocomplete="off" value="${esc(t?.note)}"></label>
    </div>`;
}

function tradeDialog(a, kind, t = null) {
  return openDialog({
    title: `${t ? "Modifica" : kind === "sell" ? "Vendi" : "Nuovo acquisto"} · ${shortName(a)}`,
    submitLabel: t ? "Salva" : kind === "sell" ? "Registra vendita" : "Registra acquisto",
    render(body) {
      body.innerHTML = tradeFields(kind, a, t);
      const all = $("[data-all]", body);
      if (all) all.addEventListener("click", () => { $('[name="shares"]', body).value = "tutte"; });
    },
    async onSubmit(form) {
      const data = { kind, ...formData(form) };
      const res = t ? await api("PUT", `/api/trades/${t.id}`, data) : await api("POST", `/api/assets/${a.id}/trades`, data);
      await afterChange(t ? "Operazione aggiornata" : kind === "sell" ? "Vendita registrata" : "Acquisto registrato");
      return res;
    },
  });
}

function addAssetDialog() {
  const d = view.data;
  let picked = null;
  let seq = 0;
  return openDialog({
    title: `Nuovo asset · ${d.account.name}`,
    wide: true,
    submitLabel: "Aggiungi",
    render(body) {
      body.innerHTML = `
        <label class="field">Cerca per ticker Yahoo, ISIN o nome
          <div class="row-actions"><input class="input grow" name="q" autocomplete="off" placeholder="es. VWCE.DE, IE00BK5BQT80, Apple">
          <button class="btn btn-sm" type="button" data-search>Cerca</button></div></label>
        <div class="search-results" data-results></div>
        <div class="picked" data-picked hidden></div>
        <div data-offline hidden>
          <p class="dlg-note">Non è possibile verificare il ticker su Yahoo (offline?). Puoi aggiungerlo indicando la valuta di quotazione: i prezzi arriveranno al prossimo aggiornamento.</p>
          <label class="field">Valuta di quotazione<input name="currency" maxlength="4" placeholder="EUR"></label>
        </div>
        <h3 class="sub-title">Primo acquisto</h3>
        ${tradeFields("buy", null)}`;
      const q = $('[name="q"]', body);
      const results = $("[data-results]", body);
      const pickedBox = $("[data-picked]", body);
      const run = async () => {
        const text = q.value.trim();
        if (!text) return;
        const my = ++seq;
        results.innerHTML = `<div class="muted small">Ricerca…</div>`;
        try {
          const list = await api("GET", `/api/market/search?q=${encodeURIComponent(text)}`);
          if (my !== seq) return;
          const raw = { symbol: text.toUpperCase(), name: "Usa il ticker così come scritto", exchange: "", type: "" };
          const items = list.slice(0, 8).concat(list.some((x) => x.symbol === raw.symbol) || /\s/.test(text) ? [] : [raw]);
          results.innerHTML = items.map((x, i) => `<button type="button" class="result" data-i="${i}">
            <b>${esc(x.symbol)}</b><span>${esc(x.name)}</span><em>${esc([x.exchange, x.type].filter(Boolean).join(" · "))}</em></button>`).join("");
          $$("[data-i]", results).forEach((b) => b.addEventListener("click", () => {
            picked = items[Number(b.dataset.i)];
            results.innerHTML = "";
            pickedBox.hidden = false;
            pickedBox.innerHTML = `<b>${esc(picked.symbol)}</b> ${esc(picked.name === raw.name ? "" : picked.name)} <button type="button" class="link" data-change>cambia</button>`;
            $("[data-change]", pickedBox).addEventListener("click", () => { picked = null; pickedBox.hidden = true; q.focus(); });
          }));
        } catch (e) {
          results.innerHTML = `<div class="neg small">${esc(e.message)}</div>`;
          $("[data-offline]", body).hidden = false;
        }
      };
      $("[data-search]", body).addEventListener("click", run);
      q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); run(); } });
    },
    async onSubmit(form) {
      const data = formData(form);
      const ticker = picked ? picked.symbol : data.q.trim().toUpperCase();
      if (!ticker) throw new Error("Cerca e scegli uno strumento.");
      delete data.q;
      const res = await api("POST", `/api/investments/${d.account.id}/assets`, {
        ...data, ticker, input_symbol: form.elements.q.value.trim(),
        name: picked && picked.name !== "Usa il ticker così come scritto" ? picked.name : undefined,
      });
      await afterChange(`${res.ticker} aggiunto`);
      return res;
    },
  });
}

function editAssetDialog(a) {
  return openDialog({
    title: `Modifica · ${a.ticker}`,
    render(body, { close }) {
      body.innerHTML = `
        <label class="field">Nome<input name="name" maxlength="120" value="${esc(a.name)}"></label>
        <label class="field">Ticker Yahoo<input name="ticker" maxlength="24" value="${esc(a.ticker)}">
          <span class="hint">Cambialo se lo strumento è quotato su un'altra borsa (es. .MI, .DE, .AS).</span></label>
        <div class="danger-zone"><div><b>Elimina asset</b><div class="hint">Elimina anche tutti i suoi acquisti e vendite: la liquidità torna sul conto.</div></div>
          <button type="button" class="btn btn-sm btn-danger" data-del>${ICON.trash}Elimina</button></div>`;
      $("[data-del]", body).addEventListener("click", async () => {
        if (!(await confirmDialog("Elimina asset", `Eliminare ${esc(a.ticker)} con ${a.trades.length} operazion${a.trades.length === 1 ? "e" : "i"}?`, { confirmLabel: "Elimina" }))) return;
        try {
          await api("DELETE", `/api/assets/${a.id}`);
          close();
          await afterChange("Asset eliminato");
        } catch (e) { toast(e.message, true); }
      });
    },
    async onSubmit(form) {
      const res = await api("PUT", `/api/assets/${a.id}`, formData(form));
      await afterChange("Asset aggiornato");
      return res;
    },
  });
}

function detailDialog(a) {
  return openDialog({
    title: `${shortName(a)} · ${a.ticker}`,
    wide: true,
    cancelLabel: "Chiudi",
    render(body, { close }) {
      const last = a.last_date ? `ultimo prezzo ${num(a.last_price, 4)} ${esc(a.currency)} del ${dateFmt(a.last_date)}` : "";
      body.innerHTML = `
        <div class="muted small">${esc(a.name)} · ${esc(a.exchange || "")} ${last ? "· " + last : ""}</div>
        ${a.error ? `<div class="err">${esc(a.error)}</div>` : `
        <div class="detail-kpis">
          <div class="kpi"><div class="label">Valore</div><div class="v fig">${m(a.value)}</div></div>
          <div class="kpi"><div class="label">Investito</div><div class="v fig">${m(a.invested)}</div></div>
          <div class="kpi"><div class="label">Guadagno</div><div class="v fig ${tone(a.gain)}">${sm(a.gain)}</div></div>
          <div class="kpi"><div class="label">Realizzato</div><div class="v fig ${tone(a.realized)}">${sm(a.realized)}</div></div>
        </div>
        <div class="chart detail-chart" data-chart></div>`}
        <h3 class="sub-title">Operazioni</h3>
        <div class="table-card"><div><table class="table compact">
          <thead><tr><th>Data</th><th>Tipo</th><th class="num">Importo</th><th class="num">Quote</th><th class="num hide-sm">Prezzo</th><th class="num hide-sm">Realizzato</th><th class="actions"></th></tr></thead>
          <tbody>${a.trades.map((t) => `<tr>
            <td>${dateFmt(t.date)}${t.note ? `<div class="cell-sub">${esc(t.note)}</div>` : ""}</td>
            <td><span class="kind-tag ${t.kind === "buy" ? "expense" : "income"}">${t.kind === "buy" ? "Acquisto" : "Vendita"}</span></td>
            <td class="num">${m(t.amount)}${t.fee ? `<div class="cell-sub">comm. ${m(t.fee)}</div>` : ""}</td>
            <td class="num">${t.shares ? qty(t.shares, 6) : "—"}</td>
            <td class="num hide-sm">${t.exec_price ? m(t.exec_price, 4) : "—"}</td>
            <td class="num hide-sm ${tone(t.realized)}">${t.realized ? sm(t.realized) : ""}</td>
            <td class="actions"><button type="button" class="icon-btn" title="Modifica" data-edit="${t.id}">${ICON.edit}</button>
              <button type="button" class="icon-btn danger" title="Elimina" data-del="${t.id}">${ICON.trash}</button></td></tr>`).join("")}
          </tbody></table></div></div>`;
      const chart = $("[data-chart]", body);
      if (chart && a.series) requestAnimationFrame(() => drawChart(chart, a.series, { axes: true, interactive: true, currency: acctCur() }));
      $$("[data-edit]", body).forEach((b) => b.addEventListener("click", () => {
        const t = a.trades.find((x) => x.id === Number(b.dataset.edit));
        close();
        tradeDialog(a, t.kind, t);
      }));
      $$("[data-del]", body).forEach((b) => b.addEventListener("click", async () => {
        const t = a.trades.find((x) => x.id === Number(b.dataset.del));
        if (!(await confirmDialog("Elimina operazione", `Eliminare ${t.kind === "buy" ? "l'acquisto" : "la vendita"} del ${dateFmt(t.date)} (${m(t.amount)})?`, { confirmLabel: "Elimina" }))) return;
        try {
          await api("DELETE", `/api/trades/${t.id}`);
          close();
          await afterChange("Operazione eliminata");
        } catch (e) { toast(e.message, true); }
      }));
    },
  });
}

function ptImportDialog() {
  const d = view.data;
  let data = null;
  const sources = state.accounts.filter((a) => !a.archived && a.id !== d.account.id && a.currency === d.account.currency);
  return openDialog({
    title: `Importa da PortfolioTracker · ${d.account.name}`,
    wide: true,
    submitLabel: "Importa",
    render(body, { dialog }) {
      const submit = $('button[type="submit"]', dialog);
      submit.disabled = true;
      body.innerHTML = `
        <p class="dlg-note">Scegli il file <span class="mono">portfolio.json</span> di PortfolioTracker. Ogni contributo diventa un acquisto su questo conto;
          i soldi arrivano dalla liquidità del conto oppure da un altro conto, con un trasferimento per ogni contributo.</p>
        <div class="grid2">
          <label class="field">File<input type="file" accept=".json,application/json" data-file class="file-input"></label>
          <label class="field">Provenienza dei soldi<select data-source>
            <option value="">Liquidità del conto (${m(d.summary.liquidity)})</option>
            ${sources.map((a) => `<option value="${a.id}">Trasferimenti da ${esc(a.name)}</option>`).join("")}</select></label>
        </div>
        <div data-summary></div>`;
      $("[data-file]", body).addEventListener("change", async (ev) => {
        const f = ev.target.files[0];
        if (!f) return;
        data = await f.arrayBuffer();
        try {
          const s = await api("POST", `/api/investments/${d.account.id}/portfoliotracker/preview`, data);
          $("[data-summary]", body).innerHTML = `
            <p>${s.assets.length} asset, ${s.contributions} contributi dal ${dateFmt(s.first_date)} per <b>${money(s.total, s.base_currency)}</b>.</p>
            <div class="table-card"><div><table class="table compact"><thead><tr><th>Ticker</th><th>Nome</th><th class="num">Contributi</th><th class="num">Importo</th></tr></thead>
            <tbody>${s.assets.map((a) => `<tr><td>${esc(a.ticker)}</td><td>${esc(a.name)}</td><td class="num">${a.contributions}</td><td class="num">${money(a.amount, s.base_currency)}</td></tr>`).join("")}</tbody></table></div></div>`;
          submit.disabled = false;
        } catch (e) {
          $("[data-summary]", body).innerHTML = `<div class="dlg-error">${esc(e.message)}</div>`;
          submit.disabled = true;
        }
      });
    },
    async onSubmit(form) {
      const source = form.querySelector("[data-source]").value;
      const res = await api("POST", `/api/investments/${d.account.id}/portfoliotracker${source ? `?source=${source}` : ""}`, data);
      await afterChange(`${res.assets} asset e ${res.buys} acquisti importati`);
      return res;
    },
  });
}

export default { mount, show };
