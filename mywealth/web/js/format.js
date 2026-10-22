/* myWealth — number formatting, and the single place where amounts are hidden (SPEC §8.7).
   No DOM access, so it is also loaded by the Node tests. */

/** Number format (setting): it-IT "1.234,56" or en-GB "1,234.56". */
export let NUM_LOCALE = "it-IT";
export function setNumberLocale(loc) { NUM_LOCALE = loc === "en-GB" ? "en-GB" : "it-IT"; }

// ------------------------------------------------------------ hidden amounts --
/** Shown in place of a hidden figure; the currency code stays visible next to it. */
export const MASK = "•••••";
const MASK_SHORT = "•••";
let masked = false;
export const isMasked = () => masked;
/** Hide (or show again) every amount, share quantity and percentage formatted below. */
export function setMasked(on) { masked = !!on; }

// ---------------------------------------------------------------- formatting --
const fmtCache = {};
function moneyFormatter(cur, dec) {
  const k = `${NUM_LOCALE}|${cur}|${dec}`;
  if (!fmtCache[k]) {
    const opts = { style: "currency", currency: cur, currencyDisplay: "code", useGrouping: "always" };
    if (dec != null) { opts.minimumFractionDigits = dec; opts.maximumFractionDigits = dec; }
    fmtCache[k] = new Intl.NumberFormat(NUM_LOCALE, opts);
  }
  return fmtCache[k];
}

/** "1234.5" + "EUR" -> "1.234,50 EUR" (display only: amounts arrive as decimal strings). */
export function money(value, cur = "EUR", dec) {
  if (value == null || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!isFinite(n)) return "—";
  if (masked) return `${MASK} ${cur}`;
  // "currencyDisplay: code" puts the code before or after depending on the locale: normalise
  const parts = moneyFormatter(cur, dec).formatToParts(n);
  const numStr = parts.filter((p) => p.type !== "currency" && p.type !== "literal").map((p) => p.value).join("");
  return `${numStr} ${cur}`;
}

/** Hidden amounts lose the sign too: it would tell gains from losses. */
export const signedMoney = (v, cur, dec) => {
  if (v == null) return "—";
  const n = Number(v);
  if (masked) return money(n, cur, dec);
  return (n > 0 ? "+" : n < 0 ? "−" : "") + money(Math.abs(n), cur, dec);
};

/** Plain number, always visible: exchange rates, interest rates, market prices. */
export function num(value, maxDec = 2, minDec = 0) {
  if (value == null || value === "") return "—";
  return Number(value).toLocaleString(NUM_LOCALE, { minimumFractionDigits: minDec, maximumFractionDigits: maxDec, useGrouping: "always" });
}

/** Quantity the user holds (shares): hidden with the amounts. */
export const qty = (value, maxDec = 2) => (masked && value != null && value !== "" ? MASK : num(value, maxDec));

/** Signed percentage of a result ("+4,2%"). */
export const pct = (v, dec = 1) => (v == null || isNaN(v) ? "—" : masked ? `${MASK_SHORT}%` : (v > 0 ? "+" : v < 0 ? "−" : "") +
  Math.abs(v).toLocaleString(NUM_LOCALE, { minimumFractionDigits: dec, maximumFractionDigits: dec }) + "%");

/** Unsigned share of a total ("42,0%"), e.g. an asset's weight in the portfolio. */
export const share = (v, dec = 1) => (v == null || isNaN(v) ? "—" : masked ? `${MASK_SHORT}%` : `${num(v, dec, dec)}%`);

/** CSS class for the sign of a value; none while amounts are hidden. */
export const tone = (v) => (v == null || masked ? "" : Number(v) > 0 ? "pos" : Number(v) < 0 ? "neg" : "");

/** Short figure for chart axes and the donut centre ("12,5 Mln"). */
export const compact = (v) => (masked ? MASK_SHORT : new Intl.NumberFormat(NUM_LOCALE, { notation: "compact", maximumFractionDigits: 1 }).format(v));

/** An amount that arrives already as text (import previews). */
export const maskRaw = (text) => (masked && text != null && text !== "" ? MASK : text);
