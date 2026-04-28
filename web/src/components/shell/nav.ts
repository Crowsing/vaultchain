/**
 * App-shell navigation taxonomy. Mirrors `app/shell.jsx` (the design
 * prototype) verbatim so the visual hierarchy matches; the seven
 * primary entries appear in the desktop sidebar, while only the five
 * `MOBILE_TABS` show in the mobile bottom tab bar (Receive and
 * Settings remain reachable but not pinned to the bar).
 */
export type NavItem = {
  id: string;
  label: string;
  to: string;
  ai?: boolean;
};

export const NAV: ReadonlyArray<NavItem> = [
  { id: "dashboard", label: "Home", to: "/dashboard" },
  { id: "send", label: "Send", to: "/send" },
  { id: "receive", label: "Receive", to: "/receive" },
  { id: "contacts", label: "Contacts", to: "/contacts" },
  { id: "history", label: "Activity", to: "/history" },
  { id: "ai", label: "Assistant", to: "/ai", ai: true },
  { id: "settings", label: "Settings", to: "/settings" },
];

/** IDs of the items that appear on the mobile bottom tab bar (5 of 7). */
export const MOBILE_TABS: ReadonlyArray<string> = [
  "dashboard",
  "send",
  "contacts",
  "history",
  "ai",
];
