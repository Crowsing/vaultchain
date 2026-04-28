import { create } from "zustand";

import type { AdminUser } from "./types";

type AdminAuthState = {
  user: AdminUser | null;
  bootstrapped: boolean;
  setUser: (user: AdminUser | null) => void;
  markBootstrapped: () => void;
  clear: () => void;
};

export const useAdminAuthStore = create<AdminAuthState>((set) => ({
  user: null,
  bootstrapped: false,
  setUser: (user) => set({ user }),
  markBootstrapped: () => set({ bootstrapped: true }),
  clear: () => set({ user: null }),
}));
