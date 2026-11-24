import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { UserRole } from "../types/domain";
import { clearStoredSession, migratingSessionStorage, SESSION_KEY } from "./sessionMigration";
import { normalizeMediaUrl } from "../utils/media";

type SessionUser = {
  id: number;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  avatar?: string | null;
  role: UserRole;
};

type Tokens = {
  access: string;
  refresh: string;
};

type SessionState = {
  isAuthenticated: boolean;
  user: SessionUser | null;
  tokens: Tokens | null;
  setSession: (payload: { user: SessionUser; access: string; refresh: string }) => void;
  clearSession: () => void;
};

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      isAuthenticated: false,
      user: null,
      tokens: null,
      setSession: ({ user, access, refresh }) =>
        set({
          isAuthenticated: true,
          user: { ...user, avatar: normalizeMediaUrl(user.avatar) },
          tokens: { access, refresh }
        }),
      clearSession: () => {
        try { clearStoredSession(); } catch { /* Storage may be disabled in the browser. */ }
        set({
          isAuthenticated: false,
          user: null,
          tokens: null
        });
      }
    }),
    {
      name: SESSION_KEY,
      storage: createJSONStorage(migratingSessionStorage),
      merge: (persistedState, currentState) => {
        const state = persistedState as Partial<SessionState>;
        return {
          ...currentState,
          ...state,
          user: state.user ? { ...state.user, avatar: normalizeMediaUrl(state.user.avatar) } : null
        };
      }
    }
  )
);
