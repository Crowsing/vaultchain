import { adminApiFetch } from "./apiFetch";
import type { AdminUser } from "./types";

export type LoginResponse = {
  pre_totp_required: boolean;
};

export type TotpVerifyResponse = {
  user: {
    id: string;
    email: string;
    actor_type: string;
  };
};

export function adminLogin(input: {
  email: string;
  password: string;
}): Promise<LoginResponse> {
  return adminApiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: input,
  });
}

export function adminTotpVerify(input: {
  code: string;
}): Promise<TotpVerifyResponse> {
  return adminApiFetch<TotpVerifyResponse>("/auth/totp/verify", {
    method: "POST",
    body: input,
  });
}

export function adminLogout(): Promise<void> {
  return adminApiFetch<void>("/auth/logout", { method: "POST" });
}

export function adminMe(): Promise<AdminUser> {
  return adminApiFetch<AdminUser>("/auth/me", { method: "GET" });
}
