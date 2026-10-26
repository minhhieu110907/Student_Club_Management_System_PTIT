from datetime import datetime

from sqlalchemy import CheckConstraint, Computed, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, MYSQL_TABLE_OPTIONS


class ClubCreationRequest(Base):
    __tablename__ = "club_creation_requests"
    __table_args__ = (
        Index("ix_club_requests_mine", "requested_by", "created_at", "id"),
        Index("ix_club_requests_review", "status", "created_at", "id"),
        Index("ix_club_creation_requests_reviewed_by", "reviewed_by"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    requested_by: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    proposed_name: Mapped[str] = mapped_column(mysql.VARCHAR(160), nullable=False)
    category: Mapped[str] = mapped_column(mysql.VARCHAR(80), nullable=False)
    mission: Mapped[str] = mapped_column(mysql.TEXT, nullable=False)
    initial_plan: Mapped[str] = mapped_column(mysql.TEXT, nullable=False)
    status: Mapped[str] = mapped_column(
        mysql.ENUM("PENDING", "APPROVED", "REJECTED"), nullable=False, server_default="PENDING"
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    rejection_reason: Mapped[str | None] = mapped_column(mysql.VARCHAR(1000))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class Club(Base):
    __tablename__ = "clubs"
    __table_args__ = (
        Index("ix_clubs_discovery", "status", "category", "id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    source_request_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False),
        ForeignKey("club_creation_requests.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    name: Mapped[str] = mapped_column(mysql.VARCHAR(160), nullable=False)
    category: Mapped[str] = mapped_column(mysql.VARCHAR(80), nullable=False)
    description: Mapped[str] = mapped_column(mysql.TEXT, nullable=False)
    status: Mapped[str] = mapped_column(
        mysql.ENUM("ACTIVE", "SUSPENDED"), nullable=False, server_default="ACTIVE"
    )
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class MembershipApplication(Base):
    __tablename__ = "membership_applications"
    __table_args__ = (
        UniqueConstraint("id", "club_id", "user_id", name="uq_membership_application_identity"),
        UniqueConstraint("club_id", "user_id", "pending_guard", name="uq_membership_pending"),
        Index("ix_membership_review", "club_id", "status", "created_at", "id"),
        Index("ix_membership_app_mine", "user_id", "created_at", "id"),
        Index("ix_membership_applications_reviewed_by", "reviewed_by"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    club_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    motivation: Mapped[str | None] = mapped_column(mysql.VARCHAR(2000))
    status: Mapped[str] = mapped_column(
        mysql.ENUM("PENDING", "APPROVED", "REJECTED"), nullable=False, server_default="PENDING"
    )
    pending_guard: Mapped[int | None] = mapped_column(
        mysql.TINYINT(unsigned=False),
        Computed("CASE WHEN status = 'PENDING' THEN 1 ELSE NULL END", persisted=True),
        nullable=True,
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    rejection_reason: Mapped[str | None] = mapped_column(mysql.VARCHAR(1000))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class ClubMembership(Base):
    __tablename__ = "club_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_application_id", "club_id", "user_id"],
            ["membership_applications.id", "membership_applications.club_id", "membership_applications.user_id"],
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        UniqueConstraint("source_application_id"),
        UniqueConstraint("club_id", "user_id", "active_guard", name="uq_membership_active"),
        UniqueConstraint("id", "club_id", name="uq_membership_id_club"),
        CheckConstraint(
            "(status = 'ACTIVE' AND ended_at IS NULL) OR "
            "(status <> 'ACTIVE' AND ended_at IS NOT NULL)",
            name="ck_membership_end_state",
        ),
        Index("ix_membership_source_identity", "source_application_id", "club_id", "user_id"),
        Index("ix_membership_my_clubs", "user_id", "status", "club_id", "id"),
        Index("ix_membership_manager_list", "club_id", "status", "role", "id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    club_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    source_application_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=False))
    role: Mapped[str] = mapped_column(
        mysql.ENUM("MEMBER", "MANAGER"), nullable=False, server_default="MEMBER"
    )
    status: Mapped[str] = mapped_column(
        mysql.ENUM("ACTIVE", "LEFT", "REMOVED"), nullable=False, server_default="ACTIVE"
    )
    active_guard: Mapped[int | None] = mapped_column(
        mysql.TINYINT(unsigned=False),
        Computed("CASE WHEN status = 'ACTIVE' THEN 1 ELSE NULL END", persisted=True),
        nullable=True,
    )
    joined_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
