from datetime import datetime

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, MYSQL_TABLE_OPTIONS


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_admin_state", "status", "id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    email_normalized: Mapped[str] = mapped_column(
        mysql.VARCHAR(254, collation="utf8mb4_0900_as_cs"), nullable=False, unique=True
    )
    full_name: Mapped[str] = mapped_column(mysql.VARCHAR(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(mysql.VARCHAR(255), nullable=False)
    global_role: Mapped[str] = mapped_column(
        mysql.ENUM("STUDENT", "ADMIN"), nullable=False, server_default="STUDENT"
    )
    status: Mapped[str] = mapped_column(
        mysql.ENUM("ACTIVE", "DISABLED"), nullable=False, server_default="ACTIVE"
    )
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class RefreshTokenFamily(Base):
    __tablename__ = "refresh_token_families"
    __table_args__ = (
        CheckConstraint("absolute_expires_at > created_at", name="ck_family_lifetime"),
        CheckConstraint("purge_after >= absolute_expires_at", name="ck_family_retention"),
        Index("ix_families_user_sessions", "user_id", "revoked_at", "id"),
        Index("ix_families_cleanup", "purge_after", "id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[bytes] = mapped_column(mysql.BINARY(16), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    revoke_reason: Mapped[str | None] = mapped_column(mysql.VARCHAR(48))
    suspicious_reuse_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    purge_after: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("family_id", "generation", name="uq_token_family_generation"),
        UniqueConstraint("family_id", "current_guard", name="uq_token_one_current"),
        CheckConstraint("expires_at > created_at", name="ck_token_lifetime"),
        CheckConstraint("generation >= 0", name="ck_token_generation"),
        Index("ix_tokens_expiry_observation", "expires_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    family_id: Mapped[bytes] = mapped_column(
        mysql.BINARY(16),
        ForeignKey("refresh_token_families.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(mysql.BINARY(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    last_used_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    rotated_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    replaced_by_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=False),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        unique=True,
    )
    generation: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=False), nullable=False)
    current_guard: Mapped[int | None] = mapped_column(
        mysql.TINYINT(unsigned=False),
        Computed(
            "CASE WHEN rotated_at IS NULL AND revoked_at IS NULL THEN 1 ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
