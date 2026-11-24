import { create } from "zustand";
import { useSessionStore } from "../../store/sessionStore";
import type { GeneratedTest } from "./types";

type TestDraftState = {
  current: { draft: GeneratedTest; saveKey: string } | null;
  open: (draft: GeneratedTest) => void;
  clear: () => void;
};

export function newSaveKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  const uuid = [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
  return uuid;
}

export const useTestDraft = create<TestDraftState>((set) => ({
  current: null,
  open: (draft) => {
    set({ current: { draft, saveKey: newSaveKey() } });
  },
  clear: () => set({ current: null }),
}));

useSessionStore.subscribe((current, previous) => {
  if (current.user?.id !== previous.user?.id) useTestDraft.getState().clear();
});
