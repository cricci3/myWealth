// Regenerate the shared test vector of the smartphone file format (SPEC §16.5, §16.8):
// synthetic entries encrypted with a fixed, published TEST key and IV. Never real data.
//
//     node tools/make_mobile_vector.mjs
import { writeFileSync } from "node:fs";
import { buildCsv } from "../mobile/js/csv.js";
import { encryptFile, importKey, keyId, b64urlEncode } from "../mobile/js/crypto.js";

export const TEST_KEY = b64urlEncode(Uint8Array.from({ length: 32 }, (_, i) => i)); // 00 01 .. 1f
const IV = Uint8Array.from({ length: 12 }, (_, i) => 0xa0 + i);
const CREATED = new Date("2026-01-15T10:30:00.000Z");

const entries = [
  { id: "5b0c6f2e-4a9d-4c1e-9b7a-1f2e3d4c5b6a", kind: "expense", date: "2026-01-14", from: "Conto corrente", amount: "12.5",
    category: "Spesa alimentare", description: 'Panetteria "Da Mario"; centro', createdAt: "2026-01-14T08:15:00.000Z" },
  { id: "0d9e8f7a-6b5c-4d3e-8f2a-1b0c9d8e7f6a", kind: "transfer", date: "2026-01-15", from: "Conto corrente", to: "Conto svizzero",
    amount: "100", toAmount: "94.2", category: "Trasferimento", description: "Cambio in CHF €", createdAt: "2026-01-15T09:00:00.000Z" },
  { id: "c3d2e1f0-a9b8-4c7d-8e6f-5a4b3c2d1e0f", kind: "income", date: "2026-01-15", to: "Conto corrente", amount: "1234.56",
    category: "Stipendio", description: "", createdAt: "2026-01-15T09:30:00.000Z" },
];

const csv = buildCsv(entries);
const key = await importKey(TEST_KEY);
const kid = await keyId(Uint8Array.from({ length: 32 }, (_, i) => i));
const file = await encryptFile(csv, key, kid, CREATED, IV);
const dir = new URL("../tests/vectors/", import.meta.url);
writeFileSync(new URL("mobile-v1.csv", dir), csv);
writeFileSync(new URL("mobile-v1.txt", dir), file);
writeFileSync(new URL("mobile-v1.json", dir), JSON.stringify({ key: TEST_KEY, kid, note: "TEST key 00..1f: never use it for real data" }, null, 2) + "\n");
console.log(file);
