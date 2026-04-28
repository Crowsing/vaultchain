"""identity_user_lockout_columns — additive lockout state on identity.users.

phase1-identity-003 — adds the two columns the TOTP failure-counter handler
writes to: a non-null counter (default 0, so existing rows backfill safely)
and a nullable timestamp for the self-healing 15-minute window.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260428_120000"
down_revision = "20260428_103000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "failed_totp_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema="identity",
    )
    op.add_column(
        "users",
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until", schema="identity")
    op.drop_column("users", "failed_totp_attempts", schema="identity")
