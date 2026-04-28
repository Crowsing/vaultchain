/**
 * Zustand store holding the authed user payload.
 *
 * AC-phase1-web-005-01 hydrates this on bootstrap; AC-phase1-web-005-05
 * clears it when the global 401 interceptor fires.
 */
import { create } from "zustand";

import type { paths } from "@vaultchain/shared-types";

export type SessionStatus =
  | "idle"
  | "loading"
  | "authenticated"
  | "unauthenticated"
  | "error";

type MeResponse =
  paths["/api/v1/me"]["get"]["responses"][200]["content"]["application/json"];

export type AuthedUser = MeResponse;

type UserStore = {
  user: AuthedUser | null;
  status: SessionStatus;
  setUser: (user: AuthedUser) => void;
  setStatus: (status: SessionStatus) => void;
  clear: () => void;
};

export const useUserStore = create<UserStore>((set) => ({
  user: null,
  status: "idle",
  setUser: (user) => set({ user, status: "authenticated" }),
  setStatus: (status) => set({ status }),
  clear: () => set({ user: null, status: "unauthenticated" }),
}));
