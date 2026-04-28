# BLOCKED: phase1-admin-002

**Blocked at:** 2026-04-28T11:50:00Z
**Branch:** feature/phase1-admin-002
**Last commit:** 13889d7

## What was tried

- Read the brief end-to-end, the current `identity` package layout, and
  the alembic migrations for `identity.users`.
- Sketched the implementation plan: PasswordHasher port + bcrypt
  adapter, AdminLogin use case, admin auth dependency, four admin
  routes, OpenAPI exclusion, Click seed CLI, login.tsx + totp.tsx +
  admin apiFetch wrapper.
- Began touching `identity/domain/errors.py` and
  `identity/domain/value_objects.py` to scaffold `InvalidCredentials`,
  `SessionRequired`, `AdminRequired`, `ActorType`, `PasswordPolicy`.
- Reverted the in-progress edits when it became clear the scope and
  the brief's stated assumptions don't line up safely under the
  2-iteration CI cap.

## What failed

**1. Migration scope contradicts reality.** The brief says: "Other
admin-required columns (`password_hash`, `actor_type`, `locked_until`,
`metadata`) already provisioned by identity-001." The committed
`20260428_103000_identity_initial.py` adds:
`id, email, email_hash, status, kyc_tier, version, created_at,
updated_at`. Of the four columns the brief assumes are present, only
`locked_until` exists (added by `20260428_120000_identity_user_lockout_columns.py`,
not identity-001). `password_hash`, `actor_type`, `metadata` are
genuinely missing. AC-04, AC-05, the User aggregate update, and the
seed CLI all depend on those columns.

**2. Frontmatter `ac_count: 4` vs body `AC-01..AC-08`.** Either the
count is stale or four ACs were dropped without pruning the body.
Without operator input I can't tell which set is authoritative.

**3. Scope.** The body covers a backend port + bcrypt adapter +
PasswordPolicy VO + AdminLogin use case + admin middleware + four
admin routes + OpenAPI filter + Click seed CLI + admin frontend
(login + totp + admin-side apiFetch). That is ≥2 M briefs of work.
Phase 1's max-2-CI-iteration rule makes it dangerous to land all of
this in one PR — a single test failure on the frontend half can burn
both retries on what is fundamentally a backend change.

## What input is needed from the human

Decide one of:

1. **Expand admin-002's migration scope** to add `password_hash`,
   `actor_type`, `metadata`, `login_failure_count` (drop the "already
   provisioned" claim) and refresh `ac_count` to 8 — and accept that
   the brief is one large all-or-nothing PR.
2. **Split admin-002 into `admin-002a` (backend, ACs 1-6 + 8) and
   `admin-002b` (frontend, AC-07).** This is the most consistent
   sizing with the rest of phase 1 and keeps each PR within the
   2-iteration cap. The frontend brief depends on the backend brief.
3. **Insert a precursor brief** that retroactively extends identity-001
   to add the admin-side columns, then have admin-002 keep its narrow
   "+login_failure_count" scope.

## Suggested next step

Option 2 is the safest and most consistent. Either way the migration
must be widened and `ac_count` corrected. Until then I'll fall through
to the next ready brief on the next loop iteration.
