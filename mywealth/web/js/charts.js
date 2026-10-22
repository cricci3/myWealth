/* SVG charts (no library). Line chart ported from PortfolioTracker; bars and donut for Analytics. */
import { compact, dateFmt, esc, money, monthShort, pct, signedMoney, tone } from "./core.js";

let gradSeq = 0;
export const SERIES_COLORS = ["--a1", "--a2", "--a3", "--a4", "--a5", "--a6", "--a7", "--a8"];
export const colorVar = (i) => `var(${SERIES_COLORS[i % SERIES_COLORS.length]})`;

export function niceTicks(min, max, count = 4) {
  const span = max - min || Math.abs(max) || 1;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || step0;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) ticks.push(Math.abs(v) < 1e-9 ? 0 : v);
  return ticks;
}

/** Keep the points of the last `days` days (0 = all). */
export function sliceRange(series, days) {
  if (!series || !days || !series.dates.length) return series;
  const last = new Date(series.dates[series.dates.length - 1] + "T12:00:00");
  const from = new Date(last.getTime() - days * 864e5).toISOString().slice(0, 10);
  let i = series.dates.findIndex((d) => d >= from);
  if (i < 0) i = 0;
  if (series.dates.length - i < 2) i = Math.max(0, series.dates.length - 2);
  const cut = (arr) => (arr ? arr.slice(i) : arr);
  return {
    ...series,
    dates: series.dates.slice(i),
    value: cut(series.value),
    invested: cut(series.invested),
    assets: (series.assets || []).map((a) => ({ ...a, value: cut(a.value), invested: cut(a.invested) })),
    lines: (series.lines || []).map((l) => ({ ...l, value: cut(l.value) })),
  };
}

/**
 * Value line (with area) and invested capital as a dashed step line.
 * opts: { axes, interactive, color, hideTotal, overlays, currency, labels: {value, invested, result}, noInvested }
 *   overlays: [{ label, color, value: [], invested: [] }] extra lines on the same dates
 *   (solid = value, dashed = invested; null = not present yet).
 */
export function drawChart(el, series, opts = {}) {
  el.innerHTML = "";
  const cur = opts.currency || "EUR";
  const L = { value: "Valore", invested: "Investito", result: "Risultato", total: "Totale", ...(opts.labels || {}) };
  if (!series || series.dates.length < 2) {
    el.innerHTML = `<div class="chart-empty">Dati insufficienti per il grafico.</div>`;
    return;
  }
  const W = Math.max(el.clientWidth, 120), H = Math.max(el.clientHeight, 40);
  const pad = opts.axes ? { l: 54, r: 8, t: 10, b: 24 } : { l: 1, r: 1, t: 4, b: 2 };
  const n = series.dates.length;
  const overlays = opts.overlays || [];
  const showTotal = !opts.hideTotal;
  const showInv = showTotal && opts.axes && !opts.noInvested && series.invested;
  let vals = showTotal ? series.value.concat(showInv ? series.invested : []) : [];
  for (const o of overlays) vals = vals.concat(o.value, o.invested || []);
  vals = vals.filter((v) => v != null);
  if (!vals.length) {
    el.innerHTML = `<div class="chart-empty">Tutte le linee sono disattivate.</div>`;
    return;
  }
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) { hi += 1; lo -= 1; }
  const padY = (hi - lo) * (opts.axes ? 0.08 : 0.12);
  lo -= padY; hi += padY;
  if (opts.axes && lo < 0 && Math.min(...vals) >= 0) lo = 0;
  const x = (i) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const color = opts.color || "var(--chart-value)";
  const gid = "g" + ++gradSeq;

  const pathOf = (arr, step) => {
    let d = "", open = false;
    (arr || []).forEach((v, i) => {
      if (v == null) { open = false; return; }
      const X = x(i).toFixed(1), Y = y(v).toFixed(1);
      d += !open ? `M${X},${Y}` : step ? `H${X}V${Y}` : `L${X},${Y}`;
      open = true;
    });
    return d;
  };
  const line = pathOf(series.value, false);
  const area = `${line}L${x(n - 1).toFixed(1)},${H - pad.b}L${x(0).toFixed(1)},${H - pad.b}Z`;
  const inv = showInv ? pathOf(series.invested, true) : "";
  const overlayPaths = overlays.map((o) =>
    (o.invested ? `<path class="line-asset-invested" d="${pathOf(o.invested, true)}" style="stroke:${o.color}"/>` : "") +
    `<path class="line-asset" d="${pathOf(o.value, false)}" style="stroke:${o.color}"/>`).join("");

  let axes = "";
  if (opts.axes) {
    for (const t of niceTicks(lo, hi, 4)) {
      if (t < lo || t > hi) continue;
      axes += `<line class="grid-line" x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}"/>`;
      axes += `<text class="axis-text" x="${pad.l - 8}" y="${y(t) + 4}" text-anchor="end">${compact(t)}</text>`;
    }
    const labels = Math.min(6, Math.max(2, Math.floor((W - pad.l) / 110)));
    for (let k = 0; k < labels; k++) {
      const i = Math.round((k / (labels - 1)) * (n - 1));
      const anchor = k === 0 ? "start" : k === labels - 1 ? "end" : "middle";
      const d = series.dates[i];
      const label = (series.dates[n - 1] > series.dates[0] && daysBetween(series.dates[0], series.dates[n - 1]) < 120)
        ? dateFmt(d).slice(0, 5) : monthShort(d);
      axes += `<text class="axis-text" x="${x(i)}" y="${H - 6}" text-anchor="${anchor}">${label}</text>`;
    }
  }

  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Andamento nel tempo">
      <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" style="stop-color:${color};stop-opacity:.22"/>
        <stop offset="1" style="stop-color:${color};stop-opacity:0"/>
      </linearGradient></defs>
      ${axes}
      ${showTotal ? `<path d="${area}" fill="url(#${gid})"/>` : ""}
      ${overlayPaths}
      ${inv ? `<path class="line-invested" d="${inv}"/>` : ""}
      ${showTotal ? `<path class="line-value" d="${line}" style="stroke:${color}"/>` : ""}
      ${opts.interactive ? `<g class="hover" style="display:none"><line class="cursor" y1="${pad.t}" y2="${H - pad.b}"/>${showTotal ? `<circle class="cursor-dot" r="4" style="stroke:${color}"/>` : ""}</g>
      <rect x="${pad.l}" y="0" width="${Math.max(W - pad.l - pad.r, 1)}" height="${H}" fill="transparent"/>` : ""}
    </svg>`;

  if (!opts.interactive) return;
  const svgEl = el.querySelector("svg"), g = svgEl.querySelector(".hover");
  const tip = document.createElement("div");
  tip.className = "tip"; tip.style.display = "none";
  el.appendChild(tip);
  const move = (ev) => {
    const r = svgEl.getBoundingClientRect();
    const px = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left) * (W / r.width);
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - pad.l) / (W - pad.l - pad.r)) * (n - 1))));
    const cx = x(i), v = series.value[i], iv = series.invested ? series.invested[i] : null;
    g.style.display = "";
    g.querySelector("line").setAttribute("x1", cx); g.querySelector("line").setAttribute("x2", cx);
    const dot = g.querySelector("circle");
    if (dot && v != null) { dot.setAttribute("cx", cx); dot.setAttribute("cy", y(v)); }
    let totalRows = "";
    if (showTotal && v != null) {
      const head = overlays.length ? `<div class="th">${L.total}</div>` : "";
      totalRows = `${head}<div class="r"><span>${L.value}</span><span>${money(v, cur)}</span></div>`;
      if (showInv && iv != null) {
        const gain = v - iv;
        totalRows += `<div class="r"><span>${L.invested}</span><span>${money(iv, cur)}</span></div>
          <div class="r"><span>${L.result}</span><span class="${tone(gain)}">${signedMoney(gain, cur)} · ${pct(iv ? (gain / iv) * 100 : 0)}</span></div>`;
      }
    }
    const rows = overlays.filter((o) => o.value[i] != null).map((o) => {
      const ov = o.value[i];
      if (o.invested) {
        const oi = o.invested[i] || 0, og = ov - oi;
        return `<div class="r ra"><span><i style="background:${o.color}"></i><span class="nm">${esc(o.label)}</span></span><span>${money(ov, cur, 0)} <em>/ ${money(oi, cur, 0)}</em> <b class="${tone(og)}">${pct(oi ? (og / oi) * 100 : 0)}</b></span></div>`;
      }
      return `<div class="r ra"><span><i style="background:${o.color}"></i><span class="nm">${esc(o.label)}</span></span><span>${money(ov, cur)}</span></div>`;
    }).join("");
    const sub = overlays.some((o) => o.invested) ? `<div class="th">Valore / investito</div>` : overlays.length && showTotal ? `<div class="th">Dettaglio</div>` : "";
    tip.innerHTML = `<div class="d">${dateFmt(series.dates[i])}</div>${totalRows}${rows ? sub + rows : ""}`;
    tip.style.display = "block";
    const left = (cx / W) * r.width;
    tip.style.left = Math.min(Math.max(left + 14, 0), r.width - tip.offsetWidth) + "px";
    if (left + 14 + tip.offsetWidth > r.width) tip.style.left = Math.max(left - tip.offsetWidth - 14, 0) + "px";
  };
  const leave = () => { g.style.display = "none"; tip.style.display = "none"; };
  svgEl.addEventListener("mousemove", move);
  svgEl.addEventListener("touchmove", move, { passive: true });
  svgEl.addEventListener("mouseleave", leave);
  svgEl.addEventListener("touchend", leave);
}

const daysBetween = (a, b) => (new Date(b) - new Date(a)) / 864e5;

/**
 * Vertical grouped bars. data: { labels: [], series: [{ name, color, values: [] }] }.
 * opts: { currency, height, signed (allow negatives), formatLabel }
 */
export function drawBars(el, data, opts = {}) {
  el.innerHTML = "";
  const cur = opts.currency || "EUR";
  const n = data.labels.length;
  if (!n) { el.innerHTML = `<div class="chart-empty">Nessun dato nel periodo.</div>`; return; }
  const W = Math.max(el.clientWidth, 160), H = Math.max(el.clientHeight, 80);
  const pad = { l: 54, r: 8, t: 10, b: 24 };
  const all = data.series.flatMap((s) => s.values).filter((v) => v != null);
  let lo = Math.min(0, ...all), hi = Math.max(0, ...all);
  if (hi === lo) hi = lo + 1;
  hi += (hi - lo) * 0.06;
  if (lo < 0) lo -= (hi - lo) * 0.04;
  const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const band = (W - pad.l - pad.r) / n;
  const k = data.series.length;
  const gap = Math.min(band * 0.28, 18);
  const bw = Math.max((band - gap) / k, 2);
  let out = "";
  for (const t of niceTicks(lo, hi, 4)) {
    if (t < lo || t > hi) continue;
    out += `<line class="grid-line${t === 0 ? " zero" : ""}" x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}"/>`;
    out += `<text class="axis-text" x="${pad.l - 8}" y="${y(t) + 4}" text-anchor="end">${compact(t)}</text>`;
  }
  const every = Math.ceil(n / Math.max(1, Math.floor((W - pad.l) / 46)));
  data.labels.forEach((label, i) => {
    const x0 = pad.l + i * band + gap / 2;
    data.series.forEach((s, j) => {
      const v = s.values[i];
      if (v == null || v === 0) return;
      const top = y(Math.max(v, 0)), bottom = y(Math.min(v, 0));
      out += `<rect class="bar" x="${(x0 + j * bw).toFixed(1)}" y="${top.toFixed(1)}" width="${Math.max(bw - 1.5, 1).toFixed(1)}" height="${Math.max(bottom - top, 1).toFixed(1)}" rx="2" style="fill:${s.color}"/>`;
    });
    if (i % every === 0) {
      out += `<text class="axis-text" x="${(pad.l + i * band + band / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">${esc(opts.formatLabel ? opts.formatLabel(label) : label)}</text>`;
    }
  });
  out += `<rect class="hit" x="${pad.l}" y="0" width="${W - pad.l - pad.r}" height="${H}" fill="transparent"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Grafico a barre">${out}</svg>`;

  const svgEl = el.querySelector("svg");
  const tip = document.createElement("div");
  tip.className = "tip"; tip.style.display = "none";
  el.appendChild(tip);
  const hl = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  hl.setAttribute("class", "bar-hl");
  svgEl.insertBefore(hl, svgEl.firstChild);
  svgEl.addEventListener("mousemove", (ev) => {
    const r = svgEl.getBoundingClientRect();
    const px = (ev.clientX - r.left) * (W / r.width);
    const i = Math.floor((px - pad.l) / band);
    if (i < 0 || i >= n) { tip.style.display = "none"; hl.style.display = "none"; return; }
    hl.style.display = "";
    hl.setAttribute("x", pad.l + i * band); hl.setAttribute("y", pad.t);
    hl.setAttribute("width", band); hl.setAttribute("height", H - pad.t - pad.b);
    const label = opts.formatLabel ? opts.formatLabel(data.labels[i], true) : data.labels[i];
    tip.innerHTML = `<div class="d">${esc(label)}</div>` + data.series.map((s) =>
      `<div class="r ra"><span><i style="background:${s.color}"></i><span class="nm">${esc(s.name)}</span></span><span>${s.values[i] == null ? "—" : money(s.values[i], cur)}</span></div>`).join("") +
      (opts.extraTip ? opts.extraTip(i) : "");
    tip.style.display = "block";
    const left = ((pad.l + i * band + band) / W) * r.width;
    tip.style.left = (left + 8 + tip.offsetWidth > r.width ? Math.max(((pad.l + i * band) / W) * r.width - tip.offsetWidth - 8, 0) : left + 8) + "px";
  });
  svgEl.addEventListener("mouseleave", () => { tip.style.display = "none"; hl.style.display = "none"; });
}

/** Horizontal bars with labels, for rankings (expenses by category). items: [{label, value, color}] */
export function drawHBars(el, items, opts = {}) {
  const cur = opts.currency || "EUR";
  if (!items.length) { el.innerHTML = `<div class="chart-empty">Nessuna spesa nel periodo.</div>`; return; }
  const max = Math.max(...items.map((i) => i.value)) || 1;
  const total = items.reduce((s, i) => s + i.value, 0);
  el.innerHTML = `<div class="hbars">${items.map((i) => `
    <div class="hbar"${opts.onClick ? ` data-key="${esc(i.key)}" role="button" tabindex="0"` : ""}>
      <div class="hbar-label"><span class="nm">${esc(i.label)}</span><span class="v">${money(i.value, cur)} <em>${pct((i.value / total) * 100, 1).replace("+", "")}</em></span></div>
      <div class="hbar-track"><i style="width:${(i.value / max) * 100}%;background:${i.color}"></i></div>
    </div>`).join("")}</div>`;
  if (opts.onClick) {
    el.querySelectorAll("[data-key]").forEach((row) => {
      row.addEventListener("click", () => opts.onClick(row.dataset.key));
      row.addEventListener("keydown", (e) => { if (e.key === "Enter") opts.onClick(row.dataset.key); });
    });
  }
}

/** Donut chart. items: [{label, value, color}] */
export function drawDonut(el, items, opts = {}) {
  const cur = opts.currency || "EUR";
  const total = items.reduce((s, i) => s + i.value, 0);
  if (!total) { el.innerHTML = `<div class="chart-empty">Nessun dato.</div>`; return; }
  const R = 60, r = 38, C = 70;
  let a0 = -Math.PI / 2;
  const arcs = items.map((it) => {
    const a1 = a0 + (it.value / total) * Math.PI * 2;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const p = (ang, rad) => `${(C + rad * Math.cos(ang)).toFixed(2)},${(C + rad * Math.sin(ang)).toFixed(2)}`;
    const d = items.length === 1
      ? `M${C - R},${C}A${R},${R} 0 1 1 ${C + R},${C}A${R},${R} 0 1 1 ${C - R},${C}M${C - r},${C}A${r},${r} 0 1 0 ${C + r},${C}A${r},${r} 0 1 0 ${C - r},${C}Z`
      : `M${p(a0, R)}A${R},${R} 0 ${large} 1 ${p(a1, R)}L${p(a1, r)}A${r},${r} 0 ${large} 0 ${p(a0, r)}Z`;
    a0 = a1;
    return `<path d="${d}" style="fill:${it.color}" fill-rule="evenodd"><title>${esc(it.label)}: ${money(it.value, cur)}</title></path>`;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 140 140" class="donut" role="img" aria-label="Ripartizione">${arcs}
    <text x="70" y="67" text-anchor="middle" class="donut-label">${esc(opts.centerLabel || "Totale")}</text>
    <text x="70" y="84" text-anchor="middle" class="donut-value">${compact(total)}</text></svg>`;
}
