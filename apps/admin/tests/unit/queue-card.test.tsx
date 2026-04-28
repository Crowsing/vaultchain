import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { QueueCard } from "@/components/queue-card";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

describe("QueueCard", () => {
  it("renders label, count, and the action button", () => {
    render(
      <MemoryRouter>
        <QueueCard
          testId="qc"
          label="KYC Queue"
          count={42}
          href="/applicants"
          openLabel="Open queue"
        />
      </MemoryRouter>,
    );

    const card = screen.getByTestId("qc");
    expect(card).toHaveTextContent("KYC Queue");
    expect(screen.getByTestId("qc-count")).toHaveTextContent("42");
    expect(
      screen.getByRole("button", { name: /open queue/i }),
    ).toBeInTheDocument();
  });

  it("navigates to href when the action button is clicked", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <QueueCard
                testId="qc"
                label="X"
                count={0}
                href="/audit"
                openLabel="Open log"
              />
            }
          />
          <Route path="/audit" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: /open log/i }));
    expect(screen.getByTestId("location")).toHaveTextContent("/audit");
  });
});
