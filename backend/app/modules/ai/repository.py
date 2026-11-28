from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.ai.models import (
    AIConversation,
    AIMessage,
    AIToolExecution,
    AITurn,
    AIUsageRecord,
)
from app.modules.clubs.models import Club


def club_exists(session: Session, club_id: int) -> bool:
    stmt = select(Club.id).where(Club.id == club_id)
    return session.execute(stmt).scalar_one_or_none() is not None


def get_conversation_by_create_key_for_update(
    session: Session,
    *,
    owner_user_id: int,
    create_request_key: bytes,
) -> AIConversation | None:
    stmt = (
        select(AIConversation)
        .where(
            AIConversation.owner_user_id == owner_user_id,
            AIConversation.create_request_key == create_request_key,
            AIConversation.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_owned_conversation_for_update(
    session: Session,
    *,
    conversation_id: int,
    owner_user_id: int,
) -> AIConversation | None:
    stmt = (
        select(AIConversation)
        .where(
            AIConversation.id == conversation_id,
            AIConversation.owner_user_id == owner_user_id,
            AIConversation.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_owned_conversation(
    session: Session,
    *,
    conversation_id: int,
    owner_user_id: int,
) -> AIConversation | None:
    stmt = select(AIConversation).where(
        AIConversation.id == conversation_id,
        AIConversation.owner_user_id == owner_user_id,
        AIConversation.deleted_at.is_(None),
    )
    return session.execute(stmt).scalar_one_or_none()


def get_inflight_turn_for_update(
    session: Session,
    *,
    conversation_id: int,
) -> AITurn | None:
    stmt = (
        select(AITurn)
        .where(
            AITurn.conversation_id == conversation_id,
            AITurn.status.in_(("PENDING", "RUNNING")),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_turn_by_request_key(
    session: Session,
    *,
    conversation_id: int,
    client_request_key: bytes,
) -> AITurn | None:
    stmt = (
        select(AITurn)
        .where(
            AITurn.conversation_id == conversation_id,
            AITurn.client_request_key == client_request_key,
        )
        .execution_options(populate_existing=True)
    )
    return session.execute(stmt).scalar_one_or_none()


def get_assistant_message_for_turn(session: Session, *, turn_id: int) -> AIMessage | None:
    stmt = select(AIMessage).where(
        AIMessage.turn_id == turn_id,
        AIMessage.role == "ASSISTANT",
    )
    return session.execute(stmt).scalar_one_or_none()


def get_usage_record_for_turn(session: Session, *, turn_id: int) -> AIUsageRecord | None:
    stmt = select(AIUsageRecord).where(
        AIUsageRecord.turn_id == turn_id,
        AIUsageRecord.attempt_no == 1,
    )
    return session.execute(stmt).scalar_one_or_none()


def list_tool_executions_for_turn(session: Session, *, turn_id: int) -> list[AIToolExecution]:
    stmt = (
        select(AIToolExecution)
        .where(AIToolExecution.turn_id == turn_id)
        .order_by(AIToolExecution.invocation_no.asc())
    )
    return list(session.execute(stmt).scalars().all())


def claim_turn_completion(
    session: Session,
    *,
    turn_id: int,
    expected_generation: int,
    new_status: str,
    finished_at: datetime,
    error_code: str | None = None,
) -> bool:
    """Atomically transition a RUNNING turn only if its lease_generation still matches."""
    stmt = (
        update(AITurn)
        .where(
            AITurn.id == turn_id,
            AITurn.status == "RUNNING",
            AITurn.lease_generation == expected_generation,
        )
        .values(
            status=new_status,
            finished_at=finished_at,
            error_code=error_code,
        )
    )
    result = session.execute(stmt)
    return (result.rowcount or 0) == 1


def list_owned_conversations(
    session: Session,
    *,
    owner_user_id: int,
    page: int,
    page_size: int,
) -> tuple[list[AIConversation], int]:
    total_stmt = (
        select(func.count())
        .select_from(AIConversation)
        .where(
            AIConversation.owner_user_id == owner_user_id,
            AIConversation.deleted_at.is_(None),
        )
    )
    total = int(session.execute(total_stmt).scalar_one())
    stmt = (
        select(AIConversation)
        .where(
            AIConversation.owner_user_id == owner_user_id,
            AIConversation.deleted_at.is_(None),
        )
        .order_by(AIConversation.updated_at.desc(), AIConversation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(session.execute(stmt).scalars().all()), total


def list_conversation_messages(
    session: Session,
    *,
    conversation_id: int,
    limit: int | None = None,
) -> list[AIMessage]:
    stmt = (
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation_id)
        .order_by(AIMessage.id.asc())
    )
    if limit is not None:
        stmt = (
            select(AIMessage)
            .where(
                AIMessage.conversation_id == conversation_id,
                AIMessage.status == "SUCCEEDED",
            )
            .order_by(AIMessage.id.desc())
            .limit(limit)
        )
        rows = list(session.execute(stmt).scalars().all())
        rows.reverse()
        return rows
    return list(session.execute(stmt).scalars().all())


def create_conversation(
    session: Session,
    *,
    owner_user_id: int,
    title: str | None,
    club_context_id: int | None,
    now: datetime,
    purge_after: datetime,
    create_request_key: bytes | None = None,
) -> AIConversation:
    conversation = AIConversation(
        owner_user_id=owner_user_id,
        create_request_key=create_request_key,
        title=title,
        club_context_id=club_context_id,
        next_turn_no=1,
        created_at=now,
        updated_at=now,
        purge_after=purge_after,
    )
    session.add(conversation)
    session.flush()
    return conversation


def add_turn(session: Session, turn: AITurn) -> AITurn:
    session.add(turn)
    session.flush()
    return turn


def add_message(session: Session, message: AIMessage) -> AIMessage:
    session.add(message)
    session.flush()
    return message


def add_usage_record(session: Session, usage_record: AIUsageRecord) -> AIUsageRecord:
    session.add(usage_record)
    session.flush()
    return usage_record


def add_tool_executions(session: Session, rows: list[AIToolExecution]) -> None:
    if rows:
        session.add_all(rows)
