/* Pairing payload shown by the desktop as a QR (SPEC §16.4): key, kid and configuration.
 * A large configuration comes as several QR codes `MWQR:<i>/<n>:<part>`, read in order. */
import { b64urlDecode, keyId } from "./crypto.js";

const NATURES = ["expense", "income", "transfer"];

export class PairingError extends Error {}

/** Validate the JSON text; returns {key, kid, at, accounts: [{name, currency, decimals}], categories}. */
export async function parsePayload(text) {
  let data;
  try { data = JSON.parse(String(text).trim()); } catch (e) { throw new PairingError("Codice non valido: non è un codice di abbinamento di myWealth."); }
  if (!data || typeof data !== "object" || data.mw === undefined) throw new PairingError("Codice non valido: non è un codice di abbinamento di myWealth.");
  if (data.mw !== 1) throw new PairingError("Codice di una versione più recente di myWealth: aggiorna l'app sul telefono.");
  let raw;
  try { raw = b64urlDecode(data.key); } catch (e) { raw = null; }
  if (!raw || raw.length !== 32 || (await keyId(raw)) !== data.kid) throw new PairingError("Codice danneggiato: mostralo di nuovo sul PC.");
  const str = (v) => typeof v === "string" && v.trim() !== "";
  if (!Array.isArray(data.accounts) || !data.accounts.every((a) => Array.isArray(a) && str(a[0]) && str(a[1]))) {
    throw new PairingError("Codice danneggiato: elenco dei conti non valido.");
  }
  const cats = {};
  for (const n of NATURES) {
    const list = (data.categories || {})[n];
    if (!Array.isArray(list) || !list.every(str)) throw new PairingError("Codice danneggiato: elenco delle categorie non valido.");
    cats[n] = list;
  }
  return {
    key: data.key, kid: data.kid, at: str(data.at) ? data.at : new Date().toISOString(),
    accounts: data.accounts.map(([name, currency, decimals]) => ({ name, currency, decimals: Number.isInteger(decimals) ? decimals : 2 })),
    categories: cats,
  };
}

/** Collects the parts of a multi-QR payload; `add()` returns the full text once all are read. */
export class ChunkCollector {
  constructor() { this.parts = new Map(); this.total = 0; }

  static isChunk(text) { return /^MWQR:\d+\/\d+:/.test(text); }

  add(text) {
    const m = /^MWQR:(\d+)\/(\d+):([\s\S]*)$/.exec(text);
    if (!m) throw new PairingError("Codice non valido.");
    const i = Number(m[1]), n = Number(m[2]);
    if (!n || i < 1 || i > n) throw new PairingError("Codice non valido.");
    if (this.total && n !== this.total) { this.parts.clear(); }  // a different sequence: start again
    this.total = n;
    this.parts.set(i, m[3]);
    if (this.parts.size < n) return null;
    let out = "";
    for (let k = 1; k <= n; k++) out += this.parts.get(k);
    return out;
  }

  get count() { return this.parts.size; }
}
