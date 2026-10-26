from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, MYSQL_TABLE_OPTIONS


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_club", "club_id", "created_at", "id"),
        Index("ix_audit_resource", "resource_type", "resource_id", "created_at", "id"),
        Index("ix_audit_cleanup", "purge_after", "id"),
        Index("ix_audit_logs_actor_user_id", "actor_user_id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="SET NULL")
    )
    club_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("clubs.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(mysql.VARCHAR(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(mysql.VARCHAR(48), nullable=False)
    resource_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), nullable=False)
    request_id: Mapped[str] = mapped_column(mysql.VARCHAR(64), nullable=False)
    safe_changes: Mapped[Any | None] = mapped_column(mysql.JSON)
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    purge_after: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
