const ADMIN_CSRF_COOKIE = "admin_csrf";

export function getAdminCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const raw = document.cookie;
  if (!raw) return null;
  const target = ADMIN_CSRF_COOKIE + "=";
  for (const part of raw.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(target)) {
      const value = trimmed.slice(target.length);
      try {
        return decodeURIComponent(value);
      } catch {
        return value;
      }
    }
  }
  return null;
}

export function hasAdminPreTotpCookie(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie
    .split(";")
    .some((part) => part.trim().startsWith("admin_pre_totp="));
}
