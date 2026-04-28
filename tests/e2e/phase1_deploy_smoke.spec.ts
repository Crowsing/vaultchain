/**
 * Phase 1 deploy smoke test — gated behind PLAYWRIGHT_LIVE=1.
 *
 * Walks the user signup → magic-link → TOTP enroll → dashboard happy
 * path against a live, deployed VaultChain stack. NOT run in CI;
 * operators run it post-deploy to prove the deploy is actually live
 * (not just CI-green).
 *
 * Prerequisites for running:
 *   - VM is up, /healthz on api.<USER_DOMAIN> returns 200
 *   - Caddy issued certs for app./admin./api.<USER_DOMAIN>
 *   - SSH access to the VM (the spec greps `docker compose logs api`
 *     for the magic-link token Phase 1 surfaces in the console adapter)
 *
 * Usage:
 *   pnpm add -D @playwright/test           # one-time per workspace
 *   PLAYWRIGHT_LIVE=1 USER_DOMAIN=example.com \
 *     HETZNER_HOST=1.2.3.4 SMOKE_EMAIL=smoke+1@example.com \
 *     pnpm exec playwright test tests/e2e/phase1_deploy_smoke.spec.ts
 *
 * Phase 2 swaps the SSH log-grep step for a Resend inbox check once a
 * real email adapter is wired up.
 */

import { execSync } from "node:child_process";

import { expect, test } from "@playwright/test";

const ENABLED = process.env["PLAYWRIGHT_LIVE"] === "1";
const USER_DOMAIN = process.env["USER_DOMAIN"] ?? "";
const HETZNER_HOST = process.env["HETZNER_HOST"] ?? "";
const SMOKE_EMAIL =
  process.env["SMOKE_EMAIL"] ?? `smoke+${Date.now()}@example.com`;

test.describe("phase1 deploy smoke", () => {
  test.skip(!ENABLED, "Set PLAYWRIGHT_LIVE=1 to run this manually post-deploy.");

  test.beforeAll(() => {
    if (!USER_DOMAIN) throw new Error("USER_DOMAIN env var is required.");
    if (!HETZNER_HOST) throw new Error("HETZNER_HOST env var is required.");
  });

  test("user signup → magic-link → TOTP → dashboard", async ({ page }) => {
    const appUrl = `https://app.${USER_DOMAIN}`;

    await page.goto(`${appUrl}/signup`);
    await page.getByLabel(/email/i).fill(SMOKE_EMAIL);
    await page.getByRole("button", { name: /sign up|continue/i }).click();
    await expect(page.getByText(/check your inbox|sent/i)).toBeVisible();

    // Phase 1's email adapter is console-mode — surface the token from
    // the api container logs over SSH.
    const grep = execSync(
      `ssh deploy@${HETZNER_HOST} "docker compose -f /opt/vaultchain/docker-compose-prod.yml logs --tail=200 api" | grep -oE 'magic_link[^ ]*token=[A-Za-z0-9_-]+' | tail -1`,
      { encoding: "utf8" },
    ).trim();
    expect(grep, "magic-link token not found in api logs").not.toBe("");

    // The token may be embedded in a URL OR show up as `token=...`. The
    // app accepts both at /auth/magic-link?token=... — extract and visit.
    const tokenMatch = grep.match(/token=([A-Za-z0-9_-]+)/);
    expect(tokenMatch).not.toBeNull();
    const token = tokenMatch![1]!;

    await page.goto(`${appUrl}/auth/magic-link?token=${token}`);

    // TOTP enrollment — accept whatever form admin-002 / web-003 ships.
    // The spec is intentionally loose (uses landmarks, not exact testids)
    // so it doesn't break on minor UI tweaks.
    await expect(
      page.getByRole("heading", { name: /two-factor|totp|enroll/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Operator types the TOTP code from their authenticator. Smoke does
    // not auto-fill it — instead it pauses until the dashboard renders.
    await expect(page.getByText(/dashboard/i)).toBeVisible({
      timeout: 60_000,
    });
  });
});
