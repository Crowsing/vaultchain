import { Link } from "react-router-dom";

import { AdminShellEmpty } from "@/components/admin-shell";

export default function NotFoundRoute() {
  return (
    <AdminShellEmpty>
      <div className="card" style={{ padding: "32px", textAlign: "center" }}>
        <p
          className="muted"
          style={{ fontSize: "12px", letterSpacing: "0.08em" }}
        >
          404
        </p>
        <h1
          className="text-xl font-semibold"
          style={{ color: "var(--text-primary)", marginTop: "4px" }}
        >
          Page not found
        </h1>
        <p
          className="text-sm"
          style={{ color: "var(--text-secondary)", marginTop: "8px" }}
        >
          The page you tried to open does not exist in the admin app.
        </p>
        <Link
          to="/"
          className="btn btn-secondary btn-md"
          style={{ marginTop: "20px", display: "inline-flex" }}
        >
          Back to sign-in
        </Link>
      </div>
    </AdminShellEmpty>
  );
}
