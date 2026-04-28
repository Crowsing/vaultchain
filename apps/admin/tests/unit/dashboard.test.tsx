import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import DashboardRoute from "@/routes/dashboard";
import { useAdminAuthStore } from "@/auth/store";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderDashboard(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<DashboardRoute />} />
        <Route path="/applicants" element={<LocationProbe />} />
        <Route path="/withdrawals" element={<LocationProbe />} />
        <Route path="/transactions" element={<LocationProbe />} />
        <Route path="/audit" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DashboardRoute (AC-phase1-admin-003-02, -03)", () => {
  beforeEach(() => {
    useAdminAuthStore.setState({
      user: {
        id: "11111111-1111-1111-1111-111111111111",
        email: "admin@vaultchain.example",
        full_name: "Demo Admin",
        role: "admin",
        last_login_at: "2026-04-28T10:00:00Z",
      },
      bootstrapped: true,
    });
  });

  it("renders all four queue cards with the correct labels and zero counts", () => {
    renderDashboard();

    const labels: Array<[string, string]> = [
      ["dashboard-card-kyc", "KYC Queue"],
      ["dashboard-card-withdrawals", "Withdrawals Pending"],
      ["dashboard-card-transactions", "Recent Transactions"],
      ["dashboard-card-audit", "Audit Events Today"],
    ];
    for (const [testId, label] of labels) {
      const card = screen.getByTestId(testId);
      expect(card).toHaveTextContent(label);
      expect(screen.getByTestId(`${testId}-count`)).toHaveTextContent("0");
    }
  });

  it("renders the sidebar nav with all six sections", () => {
    renderDashboard();

    expect(screen.getByTestId("nav-dashboard")).toHaveTextContent("Dashboard");
    expect(screen.getByTestId("nav-applicants")).toHaveTextContent(
      "Applicants",
    );
    expect(screen.getByTestId("nav-transactions")).toHaveTextContent(
      "Transactions",
    );
    expect(screen.getByTestId("nav-withdrawals")).toHaveTextContent(
      "Withdrawals",
    );
    expect(screen.getByTestId("nav-users")).toHaveTextContent("Users");
    expect(screen.getByTestId("nav-audit")).toHaveTextContent("Audit");
  });

  it("navigates to /applicants when KYC Queue 'Open queue' is clicked", () => {
    renderDashboard();
    const card = screen.getByTestId("dashboard-card-kyc");
    fireEvent.click(card.querySelector("button")!);
    expect(screen.getByTestId("location")).toHaveTextContent("/applicants");
  });

  it("navigates to /withdrawals when Withdrawals card 'Open queue' is clicked", () => {
    renderDashboard();
    const card = screen.getByTestId("dashboard-card-withdrawals");
    fireEvent.click(card.querySelector("button")!);
    expect(screen.getByTestId("location")).toHaveTextContent("/withdrawals");
  });

  it("navigates to /transactions when Transactions card 'Open list' is clicked", () => {
    renderDashboard();
    const card = screen.getByTestId("dashboard-card-transactions");
    fireEvent.click(card.querySelector("button")!);
    expect(screen.getByTestId("location")).toHaveTextContent("/transactions");
  });

  it("navigates to /audit when Audit card 'Open log' is clicked", () => {
    renderDashboard();
    const card = screen.getByTestId("dashboard-card-audit");
    fireEvent.click(card.querySelector("button")!);
    expect(screen.getByTestId("location")).toHaveTextContent("/audit");
  });

  it("renders 'Last sign in' timestamp from the auth store", () => {
    renderDashboard();
    expect(screen.getByTestId("admin-shell-last-login")).toHaveTextContent(
      /Last sign in:/,
    );
  });

  it("renders the admin's email in the header", () => {
    renderDashboard();
    expect(screen.getByTestId("admin-shell-user")).toHaveTextContent(
      "admin@vaultchain.example",
    );
  });
});
