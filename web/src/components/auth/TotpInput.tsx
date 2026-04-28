/**
 * 6-digit TOTP input — only digits, autocomplete=one-time-code,
 * inputmode=numeric. The exposed shape is intentionally simple: a
 * single string state plus an onChange. AC-phase1-web-003-06.
 */
import type { ChangeEvent } from "react";

const ONLY_DIGITS = /\D/g;

export function TotpInput({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}): React.JSX.Element {
  return (
    <input
      data-testid="totp-input"
      type="text"
      inputMode="numeric"
      autoComplete="one-time-code"
      maxLength={6}
      pattern="[0-9]*"
      placeholder="••••••"
      disabled={disabled}
      value={value}
      onChange={(e: ChangeEvent<HTMLInputElement>) => {
        const cleaned = e.target.value.replace(ONLY_DIGITS, "").slice(0, 6);
        onChange(cleaned);
      }}
      className="w-full rounded-md border border-border-default bg-bg-surface px-3 py-3 text-center text-2xl tracking-[0.5em] text-text-primary focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand disabled:opacity-50"
      aria-label="6-digit verification code"
    />
  );
}
