/**
 * `/auth/signup` — email entry. Submitting calls
 * `POST /api/v1/auth/request` with mode=signup; on 202 navigates to
 * `/auth/sent?email=…&mode=signup`. AC-phase1-web-003-02.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { AuthLayout } from "@/components/auth/AuthLayout";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-fetch";
import { postAuthRequest } from "@/features/auth/api";

const schema = z.object({
  email: z.string().email("Enter a valid email address"),
});

type FormValues = z.infer<typeof schema>;

export function SignupRoute(): React.JSX.Element {
  const navigate = useNavigate();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting, isValid },
  } = useForm<FormValues>({
    mode: "onChange",
    resolver: zodResolver(schema),
  });

  const onSubmit = async (data: FormValues): Promise<void> => {
    setSubmitError(null);
    try {
      await postAuthRequest({ email: data.email, mode: "signup" });
      navigate(
        `/auth/sent?email=${encodeURIComponent(data.email)}&mode=signup`,
      );
    } catch (e) {
      if (e instanceof ApiError) {
        setSubmitError(e.message || "Could not send the link. Try again.");
      } else {
        setSubmitError("Network error. Try again.");
      }
    }
  };

  return (
    <AuthLayout
      testId="auth-signup"
      title="Create your account"
      subtitle="We'll email you a sign-in link."
    >
      <form
        noValidate
        className="flex flex-col gap-3"
        onSubmit={(e) => void handleSubmit(onSubmit)(e)}
      >
        <label htmlFor="signup-email" className="text-sm text-text-secondary">
          Email
          <input
            id="signup-email"
            data-testid="signup-email"
            type="email"
            autoComplete="email"
            inputMode="email"
            aria-invalid={errors.email ? "true" : "false"}
            className="mt-1 w-full rounded-md border border-border-default bg-bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand aria-[invalid=true]:border-danger"
            placeholder="alice@example.com"
            {...register("email")}
          />
        </label>
        {errors.email ? (
          <p data-testid="signup-email-error" className="text-xs text-danger">
            {errors.email.message}
          </p>
        ) : null}
        {submitError ? (
          <p data-testid="signup-submit-error" className="text-xs text-danger">
            {submitError}
          </p>
        ) : null}
        <Button
          type="submit"
          data-testid="signup-continue"
          disabled={!isValid || isSubmitting}
        >
          {isSubmitting ? "Sending…" : "Continue"}
        </Button>
        <p className="mt-1 text-center text-xs text-text-muted">
          Already a member?{" "}
          <button
            type="button"
            onClick={() => navigate("/auth/login")}
            className="underline-offset-2 hover:underline"
          >
            Sign in
          </button>
        </p>
      </form>
    </AuthLayout>
  );
}
