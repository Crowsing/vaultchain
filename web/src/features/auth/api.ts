/**
 * Thin typed wrappers around `apiFetch` for the identity-005 endpoints
 * the auth screens consume. Routes call these directly via TanStack
 * Query mutations.
 *
 * NOTE: We cast through `unknown` because `apiFetch`'s typed overload
 * picks the `get` operation by default; for these POST-only routes
 * the inferred response type is `void`, so we hop through `unknown`.
 */
import type { paths } from "@vaultchain/shared-types";

import { apiFetch } from "@/lib/api-fetch";

type RequestBody =
  paths["/api/v1/auth/request"]["post"]["requestBody"]["content"]["application/json"];
type RequestResponse =
  paths["/api/v1/auth/request"]["post"]["responses"][202]["content"]["application/json"];

type VerifyBody =
  paths["/api/v1/auth/verify"]["post"]["requestBody"]["content"]["application/json"];
type VerifyResponse =
  paths["/api/v1/auth/verify"]["post"]["responses"][200]["content"]["application/json"];

type EnrollResponse =
  paths["/api/v1/auth/totp/enroll"]["post"]["responses"][200]["content"]["application/json"];
type EnrollConfirmBody =
  paths["/api/v1/auth/totp/enroll/confirm"]["post"]["requestBody"]["content"]["application/json"];

type TotpVerifyBody =
  paths["/api/v1/auth/totp/verify"]["post"]["requestBody"]["content"]["application/json"];
type TotpVerifyResponse =
  paths["/api/v1/auth/totp/verify"]["post"]["responses"][200]["content"]["application/json"];

export async function postAuthRequest(
  body: RequestBody,
): Promise<RequestResponse> {
  const result = (await apiFetch("/api/v1/auth/request", {
    method: "POST",
    body,
  })) as unknown;
  return result as RequestResponse;
}

export async function postAuthVerify(
  body: VerifyBody,
): Promise<VerifyResponse> {
  const result = (await apiFetch("/api/v1/auth/verify", {
    method: "POST",
    body,
  })) as unknown;
  return result as VerifyResponse;
}

export async function postTotpEnroll(
  preTotpToken: string,
): Promise<EnrollResponse> {
  const result = (await apiFetch("/api/v1/auth/totp/enroll", {
    method: "POST",
    headers: { Authorization: `Bearer ${preTotpToken}` },
    body: {},
  })) as unknown;
  return result as EnrollResponse;
}

export async function postTotpEnrollConfirm(
  body: EnrollConfirmBody,
  preTotpToken: string,
): Promise<void> {
  await apiFetch("/api/v1/auth/totp/enroll/confirm", {
    method: "POST",
    headers: { Authorization: `Bearer ${preTotpToken}` },
    body,
  });
}

export async function postTotpVerify(
  body: TotpVerifyBody,
  preTotpToken: string,
): Promise<TotpVerifyResponse> {
  const result = (await apiFetch("/api/v1/auth/totp/verify", {
    method: "POST",
    headers: { Authorization: `Bearer ${preTotpToken}` },
    body,
  })) as unknown;
  return result as TotpVerifyResponse;
}
