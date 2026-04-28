/**
 * Frontend-visible error code registry.
 *
 * The shape mirrors the backend's `errors-reference.md` for codes that
 * UI components actually surface to the user. Codes not present here
 * fall through to the top-level error boundary's "Something went
 * wrong" branch (AC-phase1-web-002-04).
 *
 * Each subsequent brief that introduces a new user-visible code adds
 * its entry here in the same PR.
 */
export const KNOWN_CODES: Record<string, string> = {
  "identity.unauthenticated": "Please sign in",
  "identity.csrf_failed": "Your session expired — please reload and try again",
  "identity.totp_required": "Two-factor authentication is required",
  "identity.user_locked": "Account temporarily locked — try again later",
  "identity.magic_link_invalid": "This sign-in link is no longer valid",
  "identity.magic_link_expired": "This sign-in link has expired",
  "identity.magic_link_already_used": "This sign-in link has already been used",
  "identity.refresh_token_invalid": "Please sign in again",
};

export function isKnownCode(code: string): boolean {
  return Object.hasOwn(KNOWN_CODES, code);
}

export function knownCodeMessage(code: string): string | undefined {
  return KNOWN_CODES[code];
}
