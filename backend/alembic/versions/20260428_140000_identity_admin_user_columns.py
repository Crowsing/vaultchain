"""identity_admin_user_columns — admin-actor columns on identity.users.

phase1-admin-002a — adds the four columns the admin auth flow writes:

* ``password_hash`` (TEXT NULL): bcrypt hash. NULL for user-actor rows;
  enforced as required for admin-actor rows by domain rule, not DB
  constraint, so the user-side magic-link path is unaffected.
* ``actor_type`` (TEXT NOT NULL DEFAULT 'user'): discriminates user vs
  admin actor rows. CHECK constraint locks the value space.
* ``metadata`` (JSONB NOT NULL DEFAULT '{}'): admin role + future
  extensions (full_name, etc.).
* ``login_failure_count`` (INTEGER NOT NULL DEFAULT 0): password-failure
  counter, distinct from the TOTP counter ``failed_totp_attempts`` from
  the lockout migration. Both share ``locked_until``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260428_140000"
down_revision = "20260428_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.Text(), nullable=True),
        schema="identity",
    )
    op.add_column(
        "users",
        sa.Column(
            "actor_type",
            sa.Text(),
            nullable=False,
            server_default="user",
        ),
        schema="identity",
    )
    op.add_column(
        "users",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="identity",
    )
    op.add_column(
        "users",
        sa.Column(
            "login_failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema="identity",
    )
    op.create_check_constraint(
        "ck_users_actor_type",
        "users",
        "actor_type IN ('user','admin')",
        schema="identity",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_actor_type", "users", schema="identity")
    op.drop_column("users", "login_failure_count", schema="identity")
    op.drop_column("users", "metadata", schema="identity")
    op.drop_column("users", "actor_type", schema="identity")
    op.drop_column("users", "password_hash", schema="identity")
