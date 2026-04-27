"""SQLAlchemy declarative base + outbox table mapping.

`Base` is the metadata anchor every aggregate maps onto. The outbox table
`shared.domain_events` is declared here because it lives in the shared
context and is consumed by the Unit-of-Work.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, MetaData, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention=NAMING_CONVENTION,
        schema=None,
    )


class DomainEventRow(Base):
    """`shared.domain_events` — append-only outbox per ADR Section 3."""

    __tablename__ = "domain_events"
    # SQLAlchemy mapper introspection requires this as an instance attribute,
    # not ClassVar (mypy's "Cannot override instance variable" is correct here).
    __table_args__ = {"schema": "shared"}  # noqa: RUF012

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class EventHandlerLogRow(Base):
    """`shared.event_handler_log` — idempotency ledger for outbox dispatch."""

    __tablename__ = "event_handler_log"
    __table_args__ = (
        UniqueConstraint("event_id", "handler_name", name="uq_event_handler_log_event_handler"),
        {"schema": "shared"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("shared.domain_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    handler_name: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)


__all__ = ["Base", "DomainEventRow", "EventHandlerLogRow"]
