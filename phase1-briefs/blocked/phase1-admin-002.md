# BLOCKED: phase1-admin-002

**Blocked at:** 2026-04-28T11:44:30Z
**Branch:** feature/phase1-admin-002
**Last commit:** 6dd3251

## What was tried

- Read the brief end-to-end and the current `identity` package layout.
- Inspected the existing alembic migrations for the `identity.users` schema.
- Verified the `User` aggregate fields against what the brief assumes.

## What failed

The brief assumes the migration scope is "small additive — adds
`users.login_failure_count`" and that **`password_hash`, `actor_type`,
`metadata`, `locked_until` are already provisioned by identity-001**. In
reality, only `locked_until` and `failed_totp_attempts` exist on
`identity.users` after the two applied migrations:

- `20260428_103000_identity_initial.py` adds: `id, email, email_hash,
  status, kyc_tier, version, created_at, updated_at`. No
  `password_hash`, no `actor_type`, no `metadata`.
- `20260428_120000_identity_user_lockout_columns.py` adds:
  `failed_totp_attempts`, `locked_until` (these are TOTP-counter columns
  for identity-003, not the admin password counter).

The `User` aggregate (`backend/src/vaultchain/identity/domain/aggregates.py`)
similarly has no `actor_type`, `password_hash`, `login_failure_count`,
or `metadata` fields. The brief's AC-04 / AC-05 read those fields
heavily, so they have to come from somewhere.

Secondary signals:

- Frontmatter says `ac_count: 4`; the body has 8 ACs (AC-01..AC-08).
  Either the count is stale or the AC range was reduced and not pruned
  from the body.
- The 4-hour estimate is at odds with the body, which describes a
  PasswordHasher port + bcrypt adapter + AdminLogin use case + admin
  middleware + 4 admin endpoints + an OpenAPI filter + a Click CLI +
  two React routes. That is two M briefs' worth of work in one.

## What input is needed from the human

Decide one of:

1. Expand admin-002's migration scope to add `password_hash`,
   `actor_type`, `metadata`, `login_failure_count` (drop the "already
   provisioned" claim) and refresh the `ac_count` to 8.
2. Split admin-002 into `admin-002a` (backend, ACs 1-6 + 8) and
   `admin-002b` (frontend, AC-07), so each is a sane M brief.
3. Insert a precursor brief that retroactively extends identity-001 to
   include the admin-side columns, then have admin-002 keep its narrow
   "+login_failure_count" scope.

## Suggested next step

Option 2 (split) is the most consistent with the rest of phase 1's
brief sizing — admin-002a (backend) is one strict-mode brief, the
frontend piece becomes a lightweight admin-002b that depends on
admin-002a. Either way the migration scope must be widened and the
`ac_count` corrected.
