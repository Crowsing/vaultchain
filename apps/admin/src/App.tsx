import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AuthGuard } from "@/auth/AuthGuard";
import DashboardRoute from "@/routes/dashboard";
import LoginRoute from "@/routes/login";
import NotFoundRoute from "@/routes/not-found";
import TotpRoute from "@/routes/totp";
import {
  ApplicantsPlaceholder,
  AuditPlaceholder,
  TransactionsPlaceholder,
  UsersPlaceholder,
  WithdrawalsPlaceholder,
} from "@/routes/_placeholders";

export default function App() {
  return (
    <BrowserRouter>
      <AuthGuard>
        <Routes>
          <Route path="/" element={<DashboardRoute />} />
          <Route path="/dashboard" element={<DashboardRoute />} />
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/totp" element={<TotpRoute />} />
          <Route path="/applicants" element={<ApplicantsPlaceholder />} />
          <Route path="/transactions" element={<TransactionsPlaceholder />} />
          <Route path="/withdrawals" element={<WithdrawalsPlaceholder />} />
          <Route path="/users" element={<UsersPlaceholder />} />
          <Route path="/audit" element={<AuditPlaceholder />} />
          <Route path="*" element={<NotFoundRoute />} />
        </Routes>
      </AuthGuard>
    </BrowserRouter>
  );
}
