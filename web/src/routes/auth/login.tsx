/**
 * `/auth/login` — returning-user email entry. Same shape as signup
 * but mode=login. The `redirect` query string is preserved through
 * the magic-link flow so the post-auth navigation lands on the page
 * the user was originally on.
 */
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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

export function LoginRoute(): React.JSX.Element {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const redirect = params.get("redirect");
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
      await postAuthRequest({ email: data.email, mode: "login" });
      const tail = redirect ? `&redirect=${encodeURIComponent(redirect)}` : "";
      navigate(
        `/auth/sent?email=${encodeURIComponent(data.email)}&mode=login${tail}`,
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
      testId="auth-login"
      title="Welcome back"
      subtitle="We'll email you a sign-in link."
    >
      <form
        noValidate
        className="flex flex-col gap-3"
        onSubmit={(e) => void handleSubmit(onSubmit)(e)}
      >
        <label htmlFor="login-email" className="text-sm text-text-secondary">
          Email
          <input
            id="login-email"
            data-testid="login-email"
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
          <p data-testid="login-email-error" className="text-xs text-danger">
            {errors.email.message}
          </p>
        ) : null}
        {submitError ? (
          <p data-testid="login-submit-error" className="text-xs text-danger">
            {submitError}
          </p>
        ) : null}
        <Button
          type="submit"
          data-testid="login-continue"
          disabled={!isValid || isSubmitting}
        >
          {isSubmitting ? "Sending…" : "Continue"}
        </Button>
        <p className="mt-1 text-center text-xs text-text-muted">
          New here?{" "}
          <button
            type="button"
            onClick={() => navigate("/auth/signup")}
            className="underline-offset-2 hover:underline"
          >
            Create an account
          </button>
        </p>
      </form>
    </AuthLayout>
  );
}
