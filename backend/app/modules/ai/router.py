from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.request_context import get_request_id
from app.db.session import get_db_session
from app.modules.ai.config import AISettings, build_ai_settings
from app.modules.ai.schemas import (
    AIChatRequest,
    AIChatResponse,
    AIConversationDetailResponse,
    AIConversationListResponse,
)
from app.modules.ai.service import (
    chat_with_assistant,
    get_my_conversation_detail,
    list_my_conversations,
)
from app.modules.identity.dependencies import get_current_user
from app.modules.identity.schemas import CurrentUserResponse

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])
CurrentUser = Annotated[CurrentUserResponse, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]


def get_ai_settings(request: Request) -> AISettings:
    configured = getattr(request.app.state, "ai_settings", None)
    if isinstance(configured, AISettings):
        return configured
    return build_ai_settings()


@router.post("/chat", response_model=AIChatResponse)
def post_ai_chat(
    payload: AIChatRequest,
    user: CurrentUser,
    session: DatabaseSession,
    settings: Annotated[AISettings, Depends(get_ai_settings)],
) -> AIChatResponse:
    return chat_with_assistant(
        payload,
        user,
        session,
        settings=settings,
        request_id=get_request_id(),
    )


@router.get("/conversations", response_model=AIConversationListResponse)
def get_ai_conversations(
    user: CurrentUser,
    session: DatabaseSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> AIConversationListResponse:
    return list_my_conversations(user, session, page=page, page_size=page_size)


@router.get("/conversations/{conversation_id}", response_model=AIConversationDetailResponse)
def get_ai_conversation(
    conversation_id: int,
    user: CurrentUser,
    session: DatabaseSession,
) -> AIConversationDetailResponse:
    return get_my_conversation_detail(conversation_id, user, session)
