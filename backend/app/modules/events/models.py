from datetime import datetime

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, MYSQL_TABLE_OPTIONS


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("id", "club_id", name="uq_event_id_club"),
        CheckConstraint("capacity > 0", name="ck_event_capacity"),
        CheckConstraint(
            "registration_count >= 0 AND registration_count <= capacity",
            name="ck_event_count_bounds",
        ),
        CheckConstraint("ends_at > starts_at", name="ck_event_time"),
        CheckConstraint(
            "registration_closes_at > registration_opens_at",
            name="ck_event_registration_window",
        ),
        Index("ix_events_club", "club_id", "status", "starts_at", "id"),
        Index("ix_events_discovery", "status", "visibility", "starts_at", "id"),
        Index("ix_events_created_by", "created_by"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    club_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False
    )
    created_by: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(mysql.VARCHAR(200), nullable=False)
    description: Mapped[str] = mapped_column(mysql.TEXT, nullable=False)
    location: Mapped[str] = mapped_column(mysql.VARCHAR(255), nullable=False)
    status: Mapped[str] = mapped_column(
        mysql.ENUM("DRAFT", "PUBLISHED", "CANCELLED", "COMPLETED"),
        nullable=False,
        server_default="DRAFT",
    )
    visibility: Mapped[str] = mapped_column(
        mysql.ENUM("PUBLIC_STUDENTS", "CLUB_MEMBERS_ONLY"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    registration_opens_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    registration_closes_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    cancellation_deadline_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    capacity: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=False), nullable=False)
    registration_count: Mapped[int] = mapped_column(
        mysql.INTEGER(unsigned=False), nullable=False, server_default="0"
    )
    version: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=False), nullable=False, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    cancelled_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    cancellation_reason: Mapped[str | None] = mapped_column(mysql.VARCHAR(1000))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class EventRegistration(Base):
    __tablename__ = "event_registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", "active_guard", name="uq_registration_active"),
        CheckConstraint(
            "(status = 'REGISTERED' AND cancelled_at IS NULL) OR "
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL)",
            name="ck_registration_cancel_state",
        ),
        Index("ix_registration_participants", "event_id", "status", "registered_at", "id"),
        Index("ix_registration_mine", "user_id", "status", "registered_at", "id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        mysql.ENUM("REGISTERED", "CANCELLED"), nullable=False, server_default="REGISTERED"
    )
    active_guard: Mapped[int | None] = mapped_column(
        mysql.TINYINT(unsigned=False),
        Computed("CASE WHEN status = 'REGISTERED' THEN 1 ELSE NULL END", persisted=True),
        nullable=True,
    )
    registered_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    cancellation_reason: Mapped[str | None] = mapped_column(mysql.VARCHAR(100))
