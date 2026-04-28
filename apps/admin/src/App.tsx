import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AuthGuard } from "@/auth/AuthGuard";
import DashboardRoute from "@/routes/dashboard";
import LoginRoute from "@/routes/login";
import NotFoundRoute from "@/routes/not-found";
import TotpRoute from "@/routes/totp";

export default function App() {
  return (
    <BrowserRouter>
      <AuthGuard>
        <Routes>
          <Route path="/" element={<LoginRoute />} />
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/totp" element={<TotpRoute />} />
          <Route path="/dashboard" element={<DashboardRoute />} />
          <Route path="*" element={<NotFoundRoute />} />
        </Routes>
      </AuthGuard>
    </BrowserRouter>
  );
}
