import type { StateStorage } from "zustand/middleware";

export const SESSION_KEY = "repit-session";
// Compatibility adapter only: remove the previous key after a verified successful write.
export const LEGACY_SESSION_KEY = "mirtest-session";

function valid(raw: string | null) {
  if (!raw) return false;
  try {
    const value = JSON.parse(raw);
    const state = value?.state;
    if (value.version !== 0 || typeof state?.isAuthenticated !== "boolean") return false;
    return !state.isAuthenticated || (state.user && typeof state.user.id === "number"
      && typeof state.tokens?.access === "string" && typeof state.tokens?.refresh === "string");
  } catch { return false; }
}

export function clearStoredSession(storage: Pick<Storage, "removeItem"> = window.localStorage) {
  storage.removeItem(LEGACY_SESSION_KEY);
  storage.removeItem(SESSION_KEY);
}

export function migratingSessionStorage(storage: Storage = window.localStorage): StateStorage {
  return {
    getItem(name) {
      const current = storage.getItem(name);
      if (valid(current)) {
        storage.removeItem(LEGACY_SESSION_KEY);
        return current;
      }
      const previous = storage.getItem(LEGACY_SESSION_KEY);
      if (!valid(previous)) return null;
      try {
        storage.setItem(name, previous!);
        if (storage.getItem(name) === previous) storage.removeItem(LEGACY_SESSION_KEY);
      } catch {
        // Keep the readable session until storage becomes writable; retry on the next load.
      }
      return previous;
    },
    setItem(name, value) {
      storage.setItem(name, value);
      if (storage.getItem(name) === value) storage.removeItem(LEGACY_SESSION_KEY);
    },
    removeItem(name) {
      storage.removeItem(name);
      storage.removeItem(LEGACY_SESSION_KEY);
    },
  };
}
