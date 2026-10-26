from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, MYSQL_TABLE_OPTIONS


class EventTask(Base):
    __tablename__ = "event_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "club_id"],
            ["events.id", "events.club_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assignee_membership_id", "club_id"],
            ["club_memberships.id", "club_memberships.club_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(status = 'DONE' AND completed_at IS NOT NULL) OR "
            "(status <> 'DONE' AND completed_at IS NULL)",
            name="ck_task_completion",
        ),
        Index("ix_task_event_fk", "event_id", "club_id"),
        Index("ix_task_membership_fk", "assignee_membership_id", "club_id"),
        Index("ix_tasks_event_board", "event_id", "status", "id"),
        Index("ix_tasks_assignee", "assignee_membership_id", "status", "due_at", "id"),
        Index("ix_event_tasks_created_by", "created_by"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), nullable=False)
    club_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), nullable=False)
    assignee_membership_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=False))
    created_by: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(mysql.VARCHAR(200), nullable=False)
    description: Mapped[str | None] = mapped_column(mysql.TEXT)
    status: Mapped[str] = mapped_column(
        mysql.ENUM("TODO", "IN_PROGRESS", "DONE"), nullable=False, server_default="TODO"
    )
    due_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    version: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=False), nullable=False, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
