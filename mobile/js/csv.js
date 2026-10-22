/* Entries -> CSV in the desktop import format (SPEC §9) plus `id` and `creato_il` (§16.5),
 * and amount parsing with the same rules as the desktop (money.parse_decimal). */

export const COLUMNS = ["data", "tipo", "conto_origine", "conto_destinazione", "importo", "importo_destinazione",
  "categoria", "descrizione", "id", "creato_il"];
const KIND_IT = { expense: "spesa", income: "entrata", transfer: "trasferimento" };

/**
 * "1.234,56", "1234.56", "1,234.56", "12" -> "1234.56" (dot decimal, no grouping).
 * With both separators the last one is the decimal mark; one kind repeated is thousands;
 * a single one followed by exactly three digits is thousands unless the currency has 3 decimals.
 * Throws an Error with an Italian message when invalid, not positive or too precise.
 */
export function parseAmount(text, decimals = 2) {
  let s = String(text ?? "").replace(/[\s'€$£  ]/g, "");
  if (!s) throw new Error("Inserisci l'importo.");
  const comma = s.includes(","), dot = s.includes(".");
  if (comma && dot) {
    const dec = s.lastIndexOf(",") > s.lastIndexOf(".") ? "," : ".";
    s = s.split(dec === "," ? "." : ",").join("").replace(",", ".");
  } else if (comma || dot) {
    const parts = s.split(comma ? "," : ".");
    if (parts.length > 2 && !parts.slice(1).every((p) => /^\d{3}$/.test(p))) throw new Error(`Importo non valido: ${text}`);
    const thousands = parts.length > 2 || (decimals < 3 && /^\d{1,3}$/.test(parts[0]) && /^\d{3}$/.test(parts[1]));
    s = thousands ? parts.join("") : parts.join(".");
  }
  if (!/^\d+(\.\d+)?$/.test(s)) throw new Error(`Importo non valido: ${text}`);
  let [int, frac = ""] = s.split(".");
  frac = frac.replace(/0+$/, "");
  if (frac.length > decimals) throw new Error(decimals ? `Al massimo ${decimals} decimali.` : "Questa valuta non ha decimali.");
  int = int.replace(/^0+(?=\d)/, "");
  if (/^0*$/.test(int + frac)) throw new Error("L'importo deve essere maggiore di zero.");
  return frac ? `${int}.${frac}` : int;
}

/** "1234.5" -> "1.234,50" for display (it-IT grouping, fixed decimals). */
export function formatAmount(value, decimals = 2) {
  const [int, frac = ""] = String(value).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return decimals ? `${grouped},${frac.padEnd(decimals, "0")}` : grouped;
}

function field(value) {
  const s = String(value ?? "").replace(/[\r\n]+/g, " ");
  return /[;"]/.test(s) || s !== s.trim() ? `"${s.replace(/"/g, '""')}"` : s;
}

/** CSV text (UTF-8, `;`, CRLF) of the entries, in the order given. */
export function buildCsv(entries) {
  const rows = entries.map((e) => [
    e.date, KIND_IT[e.kind],
    e.kind === "income" ? "" : e.from,
    e.kind === "expense" ? "" : e.to,
    String(e.amount).replace(".", ","),
    e.kind === "transfer" && e.toAmount ? String(e.toAmount).replace(".", ",") : "",
    e.category || "", e.description || "", e.id, e.createdAt,
  ].map(field).join(";"));
  return [COLUMNS.join(";"), ...rows].join("\r\n") + "\r\n";
}

/** `mywealth-AAAAMMGG-HHMM.txt` in local time. */
export function exportFileName(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `mywealth-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}.txt`;
}
