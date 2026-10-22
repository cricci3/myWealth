/* Encrypted export file (SPEC §16.5). Only standard Web Crypto primitives: AES-256-GCM with
 * a new random 96-bit IV per file and the header as additional authenticated data.
 *
 *   MYWEALTH-ENC 1
 *   <base64url(header JSON)>.<base64url(ciphertext + tag)>
 *
 * header = {"v":1,"alg":"AES-256-GCM","kid","iv","created"}; the AAD is its base64url text,
 * exactly as written in the file. The desktop reads it with mywealth/web/js/mobilefile.js.
 */
export const MAGIC = "MYWEALTH-ENC 1";

export class FileError extends Error {}

export function b64urlEncode(bytes) {
  let bin = "";
  const arr = new Uint8Array(bytes);
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function b64urlDecode(text) {
  if (typeof text !== "string" || !/^[A-Za-z0-9_-]*$/.test(text)) throw new FileError("Testo base64 non valido.");
  const bin = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** `kid` of a raw key: first 8 bytes of its SHA-256, in hex (same as the desktop). */
export async function keyId(raw) {
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", raw));
  return [...hash.slice(0, 8)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Import the paired key as a non-extractable CryptoKey (it can be stored in IndexedDB). */
export async function importKey(keyB64) {
  const raw = b64urlDecode(keyB64);
  if (raw.length !== 32) throw new FileError("Chiave non valida.");
  return crypto.subtle.importKey("raw", raw, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}

/** Encrypt the CSV text into the file content. `iv` is only passed by tests (fixed vectors). */
export async function encryptFile(csv, key, kid, created = new Date(), iv = null) {
  const nonce = iv || crypto.getRandomValues(new Uint8Array(12));
  const header = { v: 1, alg: "AES-256-GCM", kid, iv: b64urlEncode(nonce), created: created.toISOString() };
  const headerText = b64urlEncode(new TextEncoder().encode(JSON.stringify(header)));
  const cipher = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: nonce, additionalData: new TextEncoder().encode(headerText) },
    key, new TextEncoder().encode(csv));
  return `${MAGIC}\n${headerText}.${b64urlEncode(cipher)}\n`;
}

/** Decrypt a file written by encryptFile (used by tests and to check an export). */
export async function decryptFile(text, key, kid) {
  const lines = String(text).replace(/^﻿/, "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines[0] !== MAGIC || lines.length !== 2) throw new FileError("Non è un file di myWealth.");
  const [headerText, body, extra] = lines[1].split(".");
  if (!body || extra !== undefined) throw new FileError("File danneggiato o modificato.");
  let header;
  try {
    header = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(b64urlDecode(headerText)));
  } catch (e) {
    throw new FileError("File danneggiato o modificato.");
  }
  if (header.v !== 1 || header.alg !== "AES-256-GCM") throw new FileError("Versione del file sconosciuta.");
  if (header.kid !== kid) throw new FileError("File cifrato con un'altra chiave.");
  try {
    const plain = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: b64urlDecode(header.iv), additionalData: new TextEncoder().encode(headerText) },
      key, b64urlDecode(body));
    return { csv: new TextDecoder("utf-8").decode(plain), header };
  } catch (e) {
    throw new FileError("File danneggiato o modificato.");
  }
}
