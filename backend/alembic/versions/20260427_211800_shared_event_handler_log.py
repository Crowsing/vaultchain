"""shared_event_handler_log — outbox-side idempotency ledger.

phase1-shared-004 — see brief AC-01 for column/constraint contract.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260427_211800"
down_revision = "20260427_210224"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_handler_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shared.domain_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("handler_name", sa.Text(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.UniqueConstraint("event_id", "handler_name", name="uq_event_handler_log_event_handler"),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_table("event_handler_log", schema="shared")
