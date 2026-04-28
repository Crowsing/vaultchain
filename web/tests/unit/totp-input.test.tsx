// Covers AC-phase1-web-003-06 (TOTP input behavior): only-digits, max 6,
// inputmode/autocomplete attributes for OTP autofill.

import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TotpInput } from "@/components/auth/TotpInput";

afterEach(() => {
  cleanup();
});

function ControlledHarness({
  onValue,
  initial = "",
  disabled,
}: {
  onValue?: (next: string) => void;
  initial?: string;
  disabled?: boolean;
}): React.JSX.Element {
  const [v, setV] = useState(initial);
  return (
    <TotpInput
      value={v}
      onChange={(next) => {
        setV(next);
        onValue?.(next);
      }}
      disabled={disabled}
    />
  );
}

describe("TotpInput", () => {
  it("totp_input_strips_non_digit_characters", async () => {
    const onValue = vi.fn();
    render(<ControlledHarness onValue={onValue} />);
    const user = userEvent.setup();
    const input = screen.getByTestId("totp-input");
    await user.type(input, "1a2b3c4");
    expect(input).toHaveValue("1234");
  });

  it("totp_input_truncates_to_six_digits", async () => {
    render(<ControlledHarness />);
    const user = userEvent.setup();
    const input = screen.getByTestId("totp-input");
    await user.type(input, "12345678");
    expect(input).toHaveValue("123456");
  });

  it("totp_input_has_otp_autofill_attributes", () => {
    render(<TotpInput value="" onChange={() => {}} />);
    const input = screen.getByTestId("totp-input");
    expect(input).toHaveAttribute("inputmode", "numeric");
    expect(input).toHaveAttribute("autocomplete", "one-time-code");
    expect(input).toHaveAttribute("maxlength", "6");
  });

  it("totp_input_disabled_blocks_input", async () => {
    const onValue = vi.fn();
    render(<ControlledHarness onValue={onValue} disabled />);
    const user = userEvent.setup();
    const input = screen.getByTestId("totp-input");
    await user.type(input, "123456");
    expect(onValue).not.toHaveBeenCalled();
  });
});
