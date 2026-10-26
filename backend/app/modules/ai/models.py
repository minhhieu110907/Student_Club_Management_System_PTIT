from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, MYSQL_TABLE_OPTIONS


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        Index("ix_ai_conversations_mine", "owner_user_id", "deleted_at", "updated_at", "id"),
        Index("ix_ai_conversations_cleanup", "purge_after", "id"),
        Index("ix_ai_conversations_club_context_id", "club_context_id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(mysql.VARCHAR(160))
    club_context_id: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=False), ForeignKey("clubs.id", ondelete="SET NULL")
    )
    next_turn_no: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=False), nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    purge_after: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class AITurn(Base):
    __tablename__ = "ai_turns"
    __table_args__ = (
        UniqueConstraint("id", "conversation_id", name="uq_ai_turn_id_conversation"),
        UniqueConstraint("conversation_id", "client_request_key", name="uq_ai_turn_request"),
        UniqueConstraint("conversation_id", "turn_no", name="uq_ai_turn_order"),
        UniqueConstraint("conversation_id", "inflight_guard", name="uq_ai_one_inflight_turn"),
        Index("ix_ai_turn_recovery", "status", "lease_expires_at", "id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False)
    client_request_key: Mapped[bytes] = mapped_column(mysql.BINARY(16), nullable=False)
    payload_hash: Mapped[bytes] = mapped_column(mysql.BINARY(32), nullable=False)
    turn_no: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=False), nullable=False)
    status: Mapped[str] = mapped_column(mysql.ENUM("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"), nullable=False, server_default="PENDING")
    inflight_guard: Mapped[int | None] = mapped_column(mysql.TINYINT(unsigned=False), Computed("CASE WHEN status IN ('PENDING','RUNNING') THEN 1 ELSE NULL END", persisted=True), nullable=True)
    lease_generation: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=False), nullable=False, server_default="0")
    lease_expires_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    error_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(64))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))


class AIMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        ForeignKeyConstraint(["turn_id", "conversation_id"], ["ai_turns.id", "ai_turns.conversation_id"], ondelete="CASCADE"),
        UniqueConstraint("turn_id", "role", name="uq_ai_turn_message_role"),
        Index("ix_ai_message_history", "conversation_id", "id"),
        Index("ix_ai_message_turn_fk", "turn_id", "conversation_id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), nullable=False)
    turn_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), nullable=False)
    role: Mapped[str] = mapped_column(mysql.ENUM("USER", "ASSISTANT"), nullable=False)
    status: Mapped[str] = mapped_column(mysql.ENUM("PENDING", "SUCCEEDED", "FAILED", "CANCELLED"), nullable=False)
    content: Mapped[str | None] = mapped_column(mysql.TEXT)
    source_refs: Mapped[Any | None] = mapped_column(mysql.JSON)
    data_retrieved_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class AIUsageRecord(Base):
    __tablename__ = "ai_usage_records"
    __table_args__ = (
        UniqueConstraint("turn_id", "attempt_no", name="uq_ai_usage_attempt"),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_input_tokens"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_output_tokens"),
        CheckConstraint("estimated_cost IS NULL OR estimated_cost >= 0", name="ck_ai_cost"),
        Index("ix_ai_usage_accounting", "created_at", "provider", "model"),
        Index("ix_ai_usage_cleanup", "purge_after", "id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    turn_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=False), ForeignKey("ai_turns.id", ondelete="SET NULL"))
    attempt_no: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=False), nullable=False)
    provider: Mapped[str] = mapped_column(mysql.VARCHAR(64), nullable=False)
    model: Mapped[str] = mapped_column(mysql.VARCHAR(120), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(mysql.VARCHAR(160))
    status: Mapped[str] = mapped_column(mysql.ENUM("PENDING", "SUCCEEDED", "FAILED", "TIMEOUT", "UNKNOWN"), nullable=False, server_default="PENDING")
    usage_source: Mapped[str] = mapped_column(mysql.ENUM("PROVIDER", "ESTIMATED", "UNKNOWN"), nullable=False, server_default="UNKNOWN")
    input_tokens: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=False))
    output_tokens: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=False))
    estimated_cost: Mapped[Decimal | None] = mapped_column(mysql.DECIMAL(18, 8))
    currency: Mapped[str] = mapped_column(mysql.CHAR(3), nullable=False, server_default="USD")
    pricing_reference: Mapped[str | None] = mapped_column(mysql.VARCHAR(160))
    duration_ms: Mapped[int | None] = mapped_column(mysql.INTEGER(unsigned=False))
    error_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(64))
    created_at: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    purge_after: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6), nullable=False)


class AIToolExecution(Base):
    __tablename__ = "ai_tool_executions"
    __table_args__ = (
        UniqueConstraint("turn_id", "invocation_no", name="uq_ai_tool_invocation"),
        Index("ix_ai_tool_usage_fk", "usage_record_id", "id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), primary_key=True, autoincrement=True)
    turn_id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=False), ForeignKey("ai_turns.id", ondelete="CASCADE"), nullable=False)
    usage_record_id: Mapped[int | None] = mapped_column(mysql.BIGINT(unsigned=False), ForeignKey("ai_usage_records.id", ondelete="SET NULL"))
    invocation_no: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=False), nullable=False)
    tool_name: Mapped[str] = mapped_column(mysql.VARCHAR(80), nullable=False)
    status: Mapped[str] = mapped_column(mysql.ENUM("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "DENIED", "TIMEOUT"), nullable=False, server_default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    finished_at: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    duration_ms: Mapped[int | None] = mapped_column(mysql.INTEGER(unsigned=False))
    error_code: Mapped[str | None] = mapped_column(mysql.VARCHAR(64))
    safe_error_metadata: Mapped[Any | None] = mapped_column(mysql.JSON)
