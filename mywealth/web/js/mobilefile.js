/* Encrypted files from the smartphone (SPEC §16.5), decrypted here with the Web Crypto API:
 * the Python server has no AES in its standard library. Same format as mobile/js/crypto.js
 * (the PWA, which writes them); both are checked against tests/vectors/mobile-v1.txt.
 *
 *   MYWEALTH-ENC 1
 *   <base64url(header JSON)>.<base64url(AES-256-GCM ciphertext + tag)>
 *
 * The header {"v":1,"alg":"AES-256-GCM","kid","iv","created"} is authenticated as AAD
 * (its base64url text, exactly as written), so any change to it makes decryption fail.
 */
export const MAGIC = "MYWEALTH-ENC 1";

export class MobileFileError extends Error {}

function b64urlDecode(text) {
  if (!/^[A-Za-z0-9_-]*$/.test(text)) throw new MobileFileError("File danneggiato o modificato.");
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Split and check the file; returns {header, headerText, body} without decrypting. */
export function parseFile(text) {
  const lines = String(text).replace(/^﻿/, "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length || !lines[0].startsWith("MYWEALTH-ENC ")) throw new MobileFileError("Non è un file di myWealth.");
  if (lines[0] !== MAGIC) throw new MobileFileError("Versione del file sconosciuta: aggiorna myWealth.");
  const parts = (lines[1] || "").split(".");
  if (parts.length !== 2 || lines.length > 2) throw new MobileFileError("File danneggiato o modificato.");
  let header;
  try {
    header = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(b64urlDecode(parts[0])));
  } catch (e) {
    throw new MobileFileError("File danneggiato o modificato.");
  }
  if (!header || header.v !== 1 || header.alg !== "AES-256-GCM") throw new MobileFileError("Versione del file sconosciuta: aggiorna myWealth.");
  return { header, headerText: parts[0], body: parts[1] };
}

export async function importKey(keyB64) {
  return crypto.subtle.importKey("raw", b64urlDecode(keyB64), { name: "AES-GCM" }, false, ["decrypt"]);
}

/** Decrypt a file with the paired key; returns {csv, header}. Errors are MobileFileError. */
export async function decryptFile(text, key, kid) {
  const { header, headerText, body } = parseFile(text);
  if (header.kid !== kid) throw new MobileFileError("File cifrato con un'altra chiave: rifai l'abbinamento dello smartphone.");
  let plain;
  try {
    plain = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: b64urlDecode(header.iv || ""), additionalData: new TextEncoder().encode(headerText) },
      key, b64urlDecode(body));
  } catch (e) {
    throw new MobileFileError("File danneggiato o modificato.");
  }
  return { csv: new TextDecoder("utf-8").decode(plain), header };
}
