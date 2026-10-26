from datetime import datetime

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, MYSQL_TABLE_OPTIONS


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_inbox", "user_id", "read_at", "created_at", "id"),
        Index("ix_notifications_cleanup", "purge_after", "id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(mysql.VARCHAR(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(mysql.VARCHAR(48))
    resource_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=False))
    safe_summary: Mapped[str] = mapped_column(mysql.VARCHAR(500), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    purge_after: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
