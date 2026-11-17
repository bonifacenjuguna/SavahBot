/** A very small IndexedDB helper shared by the offline cache, the outbox and the service-worker bridge (1.4.11).
 *
 * One database, three stores:
 *   cache   { key, ts, data }              last good answers of read-only API calls, so the dashboard still shows something offline
 *   outbox  { id, method, path, body, created, tries }   writes made offline, sent when the connection is back
 *   kv      { key, value }                 small settings the service worker also needs (the backend address, a read-only badge token)
 * The service worker (public/sw.js) opens the same database with the same names, so keep the two in step.
 * Every function resolves quietly (null, false or an empty list) when IndexedDB is missing or blocked (private mode): the app works without it. */
export const DB_NAME = "savahbot-pwa";
export const DB_VERSION = 1;
export type Store = "cache" | "outbox" | "kv";

let opening: Promise<IDBDatabase | null> | null = null;

export function openDb(): Promise<IDBDatabase | null> {
  if (opening) return opening;
  opening = new Promise((resolve) => {
    try {
      if (typeof indexedDB === "undefined") return resolve(null);
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains("cache")) db.createObjectStore("cache", { keyPath: "key" });
        if (!db.objectStoreNames.contains("outbox")) db.createObjectStore("outbox", { keyPath: "id" });
        if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv", { keyPath: "key" });
      };
      req.onsuccess = () => {
        const db = req.result;
        db.onversionchange = () => { db.close(); opening = null; };
        resolve(db);
      };
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch { resolve(null); }
  });
  return opening;
}

function run<T>(store: Store, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest | null, fallback: T): Promise<T> {
  return openDb().then((db) => new Promise<T>((resolve) => {
    if (!db) return resolve(fallback);
    try {
      const tx = db.transaction(store, mode);
      const req = fn(tx.objectStore(store));
      let out: unknown = fallback;
      if (req) req.onsuccess = () => { out = req.result ?? fallback; };
      tx.oncomplete = () => resolve(out as T);
      tx.onerror = tx.onabort = () => resolve(fallback);
    } catch { resolve(fallback); }
  }));
}

export const idbGet = <T>(store: Store, key: string): Promise<T | null> => run<T | null>(store, "readonly", (s) => s.get(key), null);
export const idbPut = (store: Store, value: object): Promise<boolean> => run<boolean>(store, "readwrite", (s) => { s.put(value); return null; }, false).then(() => true);
export const idbDelete = (store: Store, key: string): Promise<void> => run<void>(store, "readwrite", (s) => { s.delete(key); return null; }, undefined);
export const idbAll = <T>(store: Store): Promise<T[]> => run<T[]>(store, "readonly", (s) => s.getAll(), []);
export const idbClear = (store: Store): Promise<void> => run<void>(store, "readwrite", (s) => { s.clear(); return null; }, undefined);
export const idbCount = (store: Store): Promise<number> => run<number>(store, "readonly", (s) => s.count(), 0);

/** Stored under `kv` for the service worker. */
export const kvGet = async <T>(key: string): Promise<T | null> => (await idbGet<{ key: string; value: T }>("kv", key))?.value ?? null;
export const kvSet = (key: string, value: unknown): Promise<boolean> => idbPut("kv", { key, value });
export const kvDelete = (key: string): Promise<void> => idbDelete("kv", key);
