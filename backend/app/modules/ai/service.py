from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import AppException
from app.modules.ai.config import AISettings
from app.modules.ai.exceptions import (
    AIConversationConflictError,
    AIConversationNotFoundError,
    AIProviderTimeoutError,
)
from app.modules.ai.models import AIMessage, AIToolExecution, AITurn, AIUsageRecord
from app.modules.ai.provider import AIProvider, build_ai_provider
from app.modules.ai.repository import (
    add_message,
    add_tool_executions,
    add_turn,
    add_usage_record,
    club_exists,
    create_conversation,
    get_owned_conversation,
    get_owned_conversation_for_update,
    list_conversation_messages,
    list_owned_conversations,
)
from app.modules.ai.schemas import (
    AIChatRequest,
    AIChatResponse,
    AIConversationDetailResponse,
    AIConversationListResponse,
    AIConversationSummary,
    AIMessageItem,
    AIToolTraceItem,
)
from app.modules.ai.tool_executor import ToolExecutionTrace, bind_authenticated_request
from app.modules.identity.schemas import CurrentUserResponse

_RETENTION_DAYS = 90
_HISTORY_LIMIT = 10


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _default_tool_session_factory(
    session: Session,
) -> Callable[[], AbstractContextManager[Session]]:
    bind = session.get_bind()
    factory = sessionmaker(bind=bind, expire_on_commit=False)

    @contextmanager
    def _open_session():
        tool_session = factory()
        try:
            yield tool_session
        finally:
            tool_session.close()

    return _open_session


def chat_with_assistant(
    payload: AIChatRequest,
    user: CurrentUserResponse,
    session: Session,
    *,
    settings: AISettings,
    request_id: str,
    provider: AIProvider | None = None,
    tool_session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
) -> AIChatResponse:
    now = _utcnow()
    purge_after = now + timedelta(days=_RETENTION_DAYS)
    prompt = payload.message.strip()

    if payload.club_context_id is not None and not club_exists(session, payload.club_context_id):
        raise AppException("Club was not found", status_code=404, error_code="CLUB_NOT_FOUND")

    if payload.conversation_id is None:
        conversation = create_conversation(
            session,
            owner_user_id=user.id,
            title=prompt[:120],
            club_context_id=payload.club_context_id,
            now=now,
            purge_after=purge_after,
        )
        history: list[tuple[str, str]] = []
    else:
        conversation = get_owned_conversation_for_update(
            session,
            conversation_id=payload.conversation_id,
            owner_user_id=user.id,
        )
        if conversation is None:
            raise AIConversationNotFoundError()
        past_messages = list_conversation_messages(
            session,
            conversation_id=conversation.id,
            limit=_HISTORY_LIMIT,
        )
        history = [(item.role, item.content or "") for item in past_messages if item.content]

    turn_no = conversation.next_turn_no
    conversation.next_turn_no = turn_no + 1
    conversation.updated_at = now

    turn = AITurn(
        conversation_id=conversation.id,
        client_request_key=uuid.uuid4().bytes,
        payload_hash=hashlib.sha256(prompt.encode("utf-8")).digest(),
        turn_no=turn_no,
        status="RUNNING",
        created_at=now,
    )
    try:
        add_turn(session, turn)
    except IntegrityError as exc:
        session.rollback()
        raise AIConversationConflictError() from exc

    add_message(
        session,
        AIMessage(
            conversation_id=conversation.id,
            turn_id=turn.id,
            role="USER",
            status="SUCCEEDED",
            content=prompt,
            created_at=now,
            updated_at=now,
        ),
    )
    model_name = settings.gemini_model if settings.provider == "gemini" else "mock-scms-v1"
    usage_record = add_usage_record(
        session,
        AIUsageRecord(
            turn_id=turn.id,
            attempt_no=1,
            provider=settings.provider,
            model=model_name,
            status="PENDING",
            usage_source="UNKNOWN",
            created_at=now,
            purge_after=purge_after,
        ),
    )

    turn_id = turn.id
    conversation_id = conversation.id
    usage_id = usage_record.id
    session.commit()

    resolved_provider = provider or build_ai_provider(settings)
    resolved_factory = tool_session_factory or _default_tool_session_factory(session)
    bound_request = bind_authenticated_request(
        user,
        request_id=request_id,
        settings=settings,
        session_factory=resolved_factory,
    )

    started = time.monotonic()
    try:
        ai_result = resolved_provider.generate_reply(
            prompt=prompt,
            history=history,
            bound_request=bound_request,
        )
    except AppException as exc:
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        _record_turn_failure(
            session,
            turn_id=turn_id,
            usage_id=usage_id,
            error_code=exc.error_code,
            is_timeout=isinstance(exc, AIProviderTimeoutError),
            duration_ms=duration_ms,
            traces=bound_request.executor.traces,
        )
        raise

    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    finished_at = _utcnow()
    traces = bound_request.executor.traces

    persisted_turn = session.get(AITurn, turn_id)
    if persisted_turn is not None:
        persisted_turn.status = "SUCCEEDED"
        persisted_turn.finished_at = finished_at

    persisted_usage = session.get(AIUsageRecord, usage_id)
    if persisted_usage is not None:
        persisted_usage.status = "SUCCEEDED"
        persisted_usage.provider = ai_result.provider
        persisted_usage.model = ai_result.model
        persisted_usage.provider_request_id = ai_result.provider_request_id
        persisted_usage.input_tokens = ai_result.input_tokens
        persisted_usage.output_tokens = ai_result.output_tokens
        persisted_usage.usage_source = (
            "PROVIDER" if ai_result.input_tokens is not None else "UNKNOWN"
        )
        persisted_usage.duration_ms = duration_ms
        persisted_usage.finished_at = finished_at

    assistant_message = add_message(
        session,
        AIMessage(
            conversation_id=conversation_id,
            turn_id=turn_id,
            role="ASSISTANT",
            status="SUCCEEDED",
            content=ai_result.reply,
            source_refs=[trace.tool_name for trace in traces if trace.status == "SUCCEEDED"]
            or None,
            data_retrieved_at=finished_at if traces else None,
            created_at=finished_at,
            updated_at=finished_at,
        ),
    )
    add_tool_executions(
        session,
        _build_tool_execution_rows(
            turn_id=turn_id,
            usage_id=usage_id,
            traces=traces,
            finished_at=finished_at,
        ),
    )
    session.commit()

    return AIChatResponse(
        conversation_id=conversation_id,
        turn_id=turn_id,
        message_id=assistant_message.id,
        provider=ai_result.provider,
        model=ai_result.model,
        reply=ai_result.reply,
        tool_calls=[
            AIToolTraceItem(
                tool_name=trace.tool_name,
                status=trace.status,
                duration_ms=trace.duration_ms,
            )
            for trace in traces
        ],
        data_retrieved_at=assistant_message.data_retrieved_at,
    )


def _record_turn_failure(
    session: Session,
    *,
    turn_id: int,
    usage_id: int,
    error_code: str,
    is_timeout: bool,
    duration_ms: int,
    traces: tuple[ToolExecutionTrace, ...],
) -> None:
    finished_at = _utcnow()
    persisted_turn = session.get(AITurn, turn_id)
    if persisted_turn is not None:
        persisted_turn.status = "FAILED"
        persisted_turn.error_code = error_code[:64]
        persisted_turn.finished_at = finished_at

    persisted_usage = session.get(AIUsageRecord, usage_id)
    if persisted_usage is not None:
        persisted_usage.status = "TIMEOUT" if is_timeout else "FAILED"
        persisted_usage.error_code = error_code[:64]
        persisted_usage.duration_ms = duration_ms
        persisted_usage.finished_at = finished_at

    add_tool_executions(
        session,
        _build_tool_execution_rows(
            turn_id=turn_id,
            usage_id=usage_id,
            traces=traces,
            finished_at=finished_at,
        ),
    )
    session.commit()


def _build_tool_execution_rows(
    *,
    turn_id: int,
    usage_id: int,
    traces: tuple[ToolExecutionTrace, ...],
    finished_at: datetime,
) -> list[AIToolExecution]:
    return [
        AIToolExecution(
            turn_id=turn_id,
            usage_record_id=usage_id,
            invocation_no=trace.invocation_no,
            tool_name=trace.tool_name,
            status=trace.status,
            finished_at=finished_at,
            duration_ms=trace.duration_ms,
            error_code=trace.error_code[:64] if trace.error_code else None,
        )
        for trace in traces
    ]


def list_my_conversations(
    user: CurrentUserResponse,
    session: Session,
    *,
    page: int = 1,
    page_size: int = 20,
) -> AIConversationListResponse:
    items, total = list_owned_conversations(
        session,
        owner_user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return AIConversationListResponse(
        items=[
            AIConversationSummary(
                id=item.id,
                title=item.title,
                club_context_id=item.club_context_id,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


def get_my_conversation_detail(
    conversation_id: int,
    user: CurrentUserResponse,
    session: Session,
) -> AIConversationDetailResponse:
    conversation = get_owned_conversation(
        session,
        conversation_id=conversation_id,
        owner_user_id=user.id,
    )
    if conversation is None:
        raise AIConversationNotFoundError()
    messages = list_conversation_messages(session, conversation_id=conversation.id)
    return AIConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        club_context_id=conversation.club_context_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            AIMessageItem(
                id=msg.id,
                turn_id=msg.turn_id,
                role=msg.role,  # type: ignore[arg-type]
                status=msg.status,
                content=msg.content,
                created_at=msg.created_at,
            )
            for msg in messages
        ],
    )
