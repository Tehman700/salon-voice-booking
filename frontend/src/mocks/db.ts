import { createSeed, type MockDb } from "./seed";

const STORAGE_KEY = "salon-mock-db";

let db: MockDb | null = null;

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

/**
 * The mock "server state". In the browser it survives reloads via sessionStorage, so refresh
 * cookies and signups behave like a real backend within a tab; tests get a fresh seed each run.
 */
export function getDb(): MockDb {
  if (db) return db;
  const saved = storage()?.getItem(STORAGE_KEY);
  if (saved) {
    try {
      db = JSON.parse(saved) as MockDb;
      return db;
    } catch {
      // Corrupt snapshot: fall back to a fresh seed.
    }
  }
  db = createSeed();
  persist();
  return db;
}

export function persist() {
  if (!db) return;
  try {
    storage()?.setItem(STORAGE_KEY, JSON.stringify(db));
  } catch {
    // Storage full or blocked; the in-memory copy still works for this page.
  }
}

export function resetDb() {
  db = createSeed();
  try {
    storage()?.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
  return db;
}
