// Logic of the smartphone PWA and of the desktop decryption (SPEC §16.8), run with
// `node --test tests/js` (also from pytest, tests/test_js.py). Node's Web Crypto is the
// same standard API the browsers implement.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import * as phone from "../../mobile/js/crypto.js";
import { buildCsv, exportFileName, formatAmount, parseAmount } from "../../mobile/js/csv.js";
import { ChunkCollector, PairingError, parsePayload } from "../../mobile/js/pairing.js";
import * as desktop from "../../mywealth/web/js/mobilefile.js";

const vec = (name) => readFileSync(new URL(`../vectors/${name}`, import.meta.url), "utf-8");
const VECTOR = JSON.parse(vec("mobile-v1.json"));

test("both sides decrypt the shared vector to the expected CSV", async () => {
  const file = vec("mobile-v1.txt");
  const d = await desktop.decryptFile(file, await desktop.importKey(VECTOR.key), VECTOR.kid);
  assert.equal(d.csv, vec("mobile-v1.csv"));
  assert.deepEqual(Object.keys(d.header), ["v", "alg", "kid", "iv", "created"]);
  const p = await phone.decryptFile(file, await phone.importKey(VECTOR.key), VECTOR.kid);
  assert.equal(p.csv, d.csv);
});

test("kid is the first 8 bytes of SHA-256 of the key", async () => {
  assert.equal(await phone.keyId(phone.b64urlDecode(VECTOR.key)), VECTOR.kid);
});

test("altered header, body or key are refused", async () => {
  const file = vec("mobile-v1.txt");
  const key = await desktop.importKey(VECTOR.key);
  const [magic, line] = file.trim().split("\n");
  const [h, c] = line.split(".");
  const header = JSON.parse(Buffer.from(h, "base64url").toString());
  const forged = Buffer.from(JSON.stringify({ ...header, created: "2020-01-01T00:00:00.000Z" })).toString("base64url");
  await assert.rejects(desktop.decryptFile(`${magic}\n${forged}.${c}\n`, key, VECTOR.kid), /danneggiato o modificato/);
  const flipped = c.slice(0, 10) + (c[10] === "A" ? "B" : "A") + c.slice(11);
  await assert.rejects(desktop.decryptFile(`${magic}\n${h}.${flipped}\n`, key, VECTOR.kid), /danneggiato o modificato/);
  await assert.rejects(desktop.decryptFile(file, key, "0000000000000000"), /un'altra chiave/);
  const other = await desktop.importKey(phone.b64urlEncode(new Uint8Array(32).fill(7)));
  await assert.rejects(desktop.decryptFile(file, other, VECTOR.kid), /danneggiato o modificato/);
  await assert.rejects(desktop.decryptFile(file.replace("ENC 1", "ENC 2"), key, VECTOR.kid), /Versione del file sconosciuta/);
  await assert.rejects(desktop.decryptFile("ciao", key, VECTOR.kid), /Non è un file di myWealth/);
});

test("every export uses a new IV and round-trips", async () => {
  const raw = crypto.getRandomValues(new Uint8Array(32));
  const key = await phone.importKey(phone.b64urlEncode(raw));
  const kid = await phone.keyId(raw);
  const a = await phone.encryptFile("x;y\r\n", key, kid);
  const b = await phone.encryptFile("x;y\r\n", key, kid);
  assert.notEqual(a, b);
  assert.match(a, /^MYWEALTH-ENC 1\n[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\n$/);
  const dkey = await desktop.importKey(phone.b64urlEncode(raw));
  assert.equal((await desktop.decryptFile(a, dkey, kid)).csv, "x;y\r\n");
  assert.equal(desktop.parseFile(b).header.iv.length, 16); // 12 bytes
});

test("the phone key cannot be exported", async () => {
  const key = await phone.importKey(VECTOR.key);
  assert.equal(key.extractable, false);
  await assert.rejects(crypto.subtle.exportKey("raw", key));
});

test("amounts follow the desktop rules", () => {
  const ok = { "12": "12", "12,5": "12.5", "12.50": "12.5", "1.234,56": "1234.56", "1,234.56": "1234.56", "1.000": "1000",
    "1.000.000": "1000000", "1,234": "1234", "0,99": "0.99", " 7 ": "7", "€ 3,10": "3.1" };
  for (const [text, want] of Object.entries(ok)) assert.equal(parseAmount(text), want, text);
  assert.equal(parseAmount("1500", 0), "1500");
  assert.equal(parseAmount("12,345", 3), "12.345");
  for (const bad of ["", "abc", "0", "0,00", "-5", "1.2.3", "12,345.6.7"]) assert.throws(() => parseAmount(bad), Error, bad);
  assert.throws(() => parseAmount("12,5", 0), /decimali/);
  assert.equal(formatAmount("1234.5"), "1.234,50");
  assert.equal(formatAmount("1500", 0), "1.500");
});

test("CSV has the import header, quotes and no line breaks in fields", () => {
  const csv = buildCsv([{ id: "i", kind: "expense", date: "2026-02-01", from: "A;B", to: "ignored", amount: "3.5",
    category: "Svago", description: 'riga1\nriga2 "x"', createdAt: "t" }]);
  const [header, row, end] = csv.split("\r\n");
  assert.equal(header, "data;tipo;conto_origine;conto_destinazione;importo;importo_destinazione;categoria;descrizione;id;creato_il");
  assert.equal(row, '2026-02-01;spesa;"A;B";;3,5;;Svago;"riga1 riga2 ""x""";i;t');
  assert.equal(end, "");
  assert.equal(exportFileName(new Date(2026, 9, 2, 8, 5)), "mywealth-20261002-0805.txt");
});

const payload = async (over = {}) => {
  const raw = Uint8Array.from({ length: 32 }, (_, i) => i);
  return JSON.stringify({ mw: 1, key: phone.b64urlEncode(raw), kid: await phone.keyId(raw), at: "2026-10-22T10:00:00+00:00",
    accounts: [["Conto", "EUR", 2], ["Yen", "JPY", 0]], categories: { expense: ["Svago"], income: ["Stipendio"], transfer: [] }, ...over });
};

test("pairing payload is validated", async () => {
  const p = await parsePayload(await payload());
  assert.deepEqual(p.accounts[1], { name: "Yen", currency: "JPY", decimals: 0 });
  assert.equal(p.kid, VECTOR.kid);
  await assert.rejects(parsePayload(await payload({ kid: "ffffffffffffffff" })), PairingError);
  await assert.rejects(parsePayload(await payload({ mw: 2 })), /più recente/);
  await assert.rejects(parsePayload(await payload({ accounts: [["", "EUR"]] })), PairingError);
  await assert.rejects(parsePayload("not json"), PairingError);
});

test("multi-QR payloads are joined in order, whatever the scan order", async () => {
  const text = await payload();
  const size = 120;
  const parts = [];
  for (let i = 0; i < text.length; i += size) parts.push(text.slice(i, i + size));
  const codes = parts.map((p, i) => `MWQR:${i + 1}/${parts.length}:${p}`);
  const c = new ChunkCollector();
  assert.ok(ChunkCollector.isChunk(codes[0]) && !ChunkCollector.isChunk(text));
  let out = null;
  for (const code of [...codes].reverse().concat(codes[0])) out = c.add(code) ?? out;
  assert.equal(out, text);
});
