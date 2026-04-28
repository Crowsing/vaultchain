import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { AdminShellAuthed, AdminShellEmpty } from "@/components/admin-shell";
import { useAdminAuthStore } from "@/auth/store";

describe("AdminShellEmpty", () => {
  it("renders only a centered main column with no sidebar/header", () => {
    render(
      <AdminShellEmpty>
        <p>auth-card</p>
      </AdminShellEmpty>,
    );

    expect(screen.getByTestId("admin-shell-empty")).toBeInTheDocument();
    expect(screen.getByText("auth-card")).toBeInTheDocument();
    expect(screen.queryByTestId("admin-shell-sidebar")).toBeNull();
    expect(screen.queryByTestId("admin-shell-header")).toBeNull();
  });
});

describe("AdminShellAuthed", () => {
  beforeEach(() => {
    useAdminAuthStore.setState({
      user: {
        id: "11111111-1111-1111-1111-111111111111",
        email: "admin@vaultchain.example",
        full_name: "Demo Admin",
        role: "admin",
        last_login_at: null,
      },
      bootstrapped: true,
    });
  });

  it("renders sidebar, header, and main content slots", () => {
    render(
      <MemoryRouter>
        <AdminShellAuthed>
          <p>dashboard</p>
        </AdminShellAuthed>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("admin-shell-authed")).toBeInTheDocument();
    expect(screen.getByTestId("admin-shell-sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("admin-shell-header")).toBeInTheDocument();
    const main = screen.getByTestId("admin-shell-main");
    expect(main).toContainElement(screen.getByText("dashboard"));
  });
});
