import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AdminShellAuthed, AdminShellEmpty } from "@/components/admin-shell";

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
  it("renders sidebar, header, and main content slots", () => {
    render(
      <AdminShellAuthed>
        <p>dashboard</p>
      </AdminShellAuthed>,
    );

    expect(screen.getByTestId("admin-shell-authed")).toBeInTheDocument();
    expect(screen.getByTestId("admin-shell-sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("admin-shell-header")).toBeInTheDocument();
    const main = screen.getByTestId("admin-shell-main");
    expect(main).toContainElement(screen.getByText("dashboard"));
  });
});
