import { AdminShellAuthed } from "@/components/admin-shell";
import { adminLogout } from "@/auth/api";
import { useAdminAuthStore } from "@/auth/store";
import { useNavigate } from "react-router-dom";

export default function DashboardRoute() {
  const user = useAdminAuthStore((s) => s.user);
  const clear = useAdminAuthStore((s) => s.clear);
  const navigate = useNavigate();

  async function onLogout() {
    try {
      await adminLogout();
    } finally {
      clear();
      navigate("/login", { replace: true });
    }
  }

  return (
    <AdminShellAuthed>
      <header className="flex items-center justify-between mb-6">
        <h1
          className="text-xl font-semibold"
          style={{ color: "var(--text-primary)" }}
        >
          Dashboard
        </h1>
        <button
          type="button"
          className="btn btn-secondary btn-md"
          data-testid="admin-logout"
          onClick={onLogout}
        >
          Sign out
        </button>
      </header>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
        Welcome
        {user?.full_name
          ? ` ${user.full_name}`
          : user?.email
            ? ` ${user.email}`
            : ""}
        . Phase 3 will land applicants, transactions, withdrawals, and audit
        views here.
      </p>
    </AdminShellAuthed>
  );
}
