/* Data kept on the phone, in IndexedDB only: the pairing (non-extractable CryptoKey + kid
 * + configuration), preferences and the entries. Nothing is ever sent anywhere in clear. */

const DB_NAME = "mywealth";
const VERSION = 1;
let dbPromise = null;

function open() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv");
        if (!db.objectStoreNames.contains("entries")) db.createObjectStore("entries", { keyPath: "id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return dbPromise;
}

async function run(store, mode, fn) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode);
    let result;
    const req = fn(tx.objectStore(store));
    if (req) req.onsuccess = () => { result = req.result; };
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error("Salvataggio non riuscito."));
  });
}

export const getValue = (key) => run("kv", "readonly", (s) => s.get(key));
export const setValue = (key, value) => run("kv", "readwrite", (s) => s.put(value, key));
export const deleteValue = (key) => run("kv", "readwrite", (s) => s.delete(key));

export const allEntries = () => run("entries", "readonly", (s) => s.getAll());
export const putEntry = (entry) => run("entries", "readwrite", (s) => s.put(entry));
export const deleteEntry = (id) => run("entries", "readwrite", (s) => s.delete(id));

/** Save several entries in one transaction (e.g. marking an export). */
export async function putEntries(entries) {
  await run("entries", "readwrite", (s) => { entries.forEach((e) => s.put(e)); });
}

export async function deleteEntries(ids) {
  await run("entries", "readwrite", (s) => { ids.forEach((id) => s.delete(id)); });
}

/** Ask the browser not to evict the data when space runs low. */
export async function persist() {
  try {
    if (!navigator.storage || !navigator.storage.persist) return false;
    return (await navigator.storage.persisted()) || (await navigator.storage.persist());
  } catch (e) {
    return false;
  }
}
