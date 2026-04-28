/**
 * Top-level router config. Splits the route tree into two groups:
 *
 *   - Pre-auth (`/`, `/auth/*`): renders bare with the AuthLayout
 *     pre-auth shell. The post-auth shell is intentionally a separate
 *     component tree.
 *   - Authed: rendered inside the AppShell, gated by SessionGate.
 *     The 404 catch-all also lives here so authed users get the shell
 *     wrapped error.
 */
import {
  Navigate,
  Route,
  RouterProvider,
  createBrowserRouter,
  createRoutesFromElements,
} from "react-router-dom";

import { AppShell } from "@/components/shell/AppShell";
import { SessionGate } from "@/components/SessionGate";
import { DashboardRoute } from "@/routes/dashboard";
import { LandingRoute } from "@/routes/landing";
import { NotFoundRoute } from "@/routes/not-found";
import { PlaceholderRoute } from "@/routes/placeholder";
import { EnrollRoute } from "@/routes/auth/enroll";
import { LoginRoute } from "@/routes/auth/login";
import { SentRoute } from "@/routes/auth/sent";
import { SignupRoute } from "@/routes/auth/signup";
import { TotpRoute } from "@/routes/auth/totp";
import { VerifyRoute } from "@/routes/auth/verify";

const router = createBrowserRouter(
  createRoutesFromElements(
    <Route>
      <Route path="/" element={<LandingRoute />} />
      <Route path="/auth/signup" element={<SignupRoute />} />
      <Route path="/auth/login" element={<LoginRoute />} />
      <Route path="/auth/sent" element={<SentRoute />} />
      <Route path="/auth/verify" element={<VerifyRoute />} />
      <Route path="/auth/enroll" element={<EnrollRoute />} />
      <Route path="/auth/totp" element={<TotpRoute />} />

      <Route element={<SessionGate />}>
        <Route element={<AppShell />}>
          <Route path="dashboard" element={<DashboardRoute />} />
          <Route
            path="send"
            element={
              <PlaceholderRoute
                testId="send-placeholder"
                title="Send"
                description="Send flow lands in phase2-money."
              />
            }
          />
          <Route
            path="receive"
            element={
              <PlaceholderRoute
                testId="receive-placeholder"
                title="Receive"
                description="Receive flow lands in phase2-money."
              />
            }
          />
          <Route
            path="contacts"
            element={
              <PlaceholderRoute
                testId="contacts-placeholder"
                title="Contacts"
                description="Contacts ship in a later phase."
              />
            }
          />
          <Route
            path="history"
            element={
              <PlaceholderRoute
                testId="history-placeholder"
                title="Activity"
                description="Activity feed lands in phase3-events."
              />
            }
          />
          <Route
            path="ai"
            element={
              <PlaceholderRoute
                testId="ai-placeholder"
                title="Assistant"
                description="Assistant lands in phase4-ai."
              />
            }
          />
          <Route
            path="settings"
            element={
              <PlaceholderRoute
                testId="settings-placeholder"
                title="Settings"
                description="Settings ship in phase4-polish."
              />
            }
          />
          <Route
            path="tx/:id"
            element={
              <PlaceholderRoute
                testId="tx-placeholder"
                title="Transaction"
                description="Transaction details land in phase3-events."
              />
            }
          />
          <Route path="*" element={<NotFoundRoute />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Route>,
  ),
);

export default function App(): React.JSX.Element {
  return <RouterProvider router={router} />;
}
