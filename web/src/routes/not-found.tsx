/**
 * 404 route — renders inside the shell when authed (router config
 * places it under the AppShell layout) and stand-alone when pre-auth.
 *
 * AC-phase1-web-005-06: clear "page not found" message + back-to-home
 * button.
 */
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useUserStore } from "@/store/user-store";

export function NotFoundRoute(): React.JSX.Element {
  const status = useUserStore((s) => s.status);
  const home = status === "authenticated" ? "/dashboard" : "/auth/login";
  return (
    <div
      role="alert"
      data-testid="not-found"
      className="flex flex-col items-center gap-4 rounded-lg bg-bg-surface p-12 text-center"
    >
      <h2 className="text-2xl font-semibold text-text-primary">
        Page not found
      </h2>
      <p className="max-w-md text-sm text-text-secondary">
        The page you were looking for doesn’t exist or has moved.
      </p>
      <Button asChild>
        <Link to={home}>
          {status === "authenticated" ? "Back to dashboard" : "Back to login"}
        </Link>
      </Button>
    </div>
  );
}
