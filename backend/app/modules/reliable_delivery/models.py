from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, MYSQL_TABLE_OPTIONS


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_outbox_attempts"),
        CheckConstraint(
            "(status <> 'PROCESSING') OR "
            "(claim_token IS NOT NULL AND claimed_until IS NOT NULL)",
            name="ck_outbox_claim",
        ),
        CheckConstraint(
            "(status <> 'PUBLISHED') OR published_at IS NOT NULL",
            name="ck_outbox_published",
        ),
        Index("ix_outbox_due", "status", "next_attempt_at", "id"),
        Index("ix_outbox_reclaim", "status", "claimed_until", "id"),
        Index("ix_outbox_cleanup", "purge_after", "id"),
        Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(mysql.VARCHAR(80), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(mysql.VARCHAR(48), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), nullable=False)
    payload: Mapped[Any] = mapped_column(mysql.JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        mysql.ENUM("PENDING", "PROCESSING", "PUBLISHED", "DEAD"),
        nullable=False,
        server_default="PENDING",
    )
    attempt_count: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=False), nullable=False, server_default="0"
    )
    next_attempt_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    claim_token: Mapped[bytes | None] = mapped_column(mysql.BINARY(16))
    claimed_until: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    published_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    last_error_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(64))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    purge_after: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
