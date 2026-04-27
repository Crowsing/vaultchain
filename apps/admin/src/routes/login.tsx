import { AdminShellEmpty } from "@/components/admin-shell";

export default function LoginRoute() {
  return (
    <AdminShellEmpty>
      <div className="card" style={{ padding: "32px", textAlign: "center" }}>
        <h1
          className="text-xl font-semibold mb-1"
          style={{ color: "var(--text-primary)" }}
        >
          VaultChain Admin
        </h1>
        <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
          Sign in to continue.
        </p>

        <form
          className="stack gap-3"
          style={{ textAlign: "left" }}
          onSubmit={(e) => e.preventDefault()}
        >
          <div>
            <label className="input-label" htmlFor="admin-email">
              Email
            </label>
            <input
              id="admin-email"
              type="email"
              autoComplete="username"
              className="input"
              placeholder="admin@vaultchain.example"
              disabled
            />
          </div>
          <div>
            <label className="input-label" htmlFor="admin-password">
              Password
            </label>
            <input
              id="admin-password"
              type="password"
              autoComplete="current-password"
              className="input"
              disabled
            />
          </div>
          <button
            type="submit"
            className="btn btn-primary btn-md"
            disabled
            aria-disabled="true"
          >
            Sign in
          </button>
        </form>

        <p className="muted" style={{ fontSize: "12px", marginTop: "20px" }}>
          Admin access · audited · all actions logged.
        </p>
      </div>
    </AdminShellEmpty>
  );
}
