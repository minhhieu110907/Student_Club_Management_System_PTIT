from __future__ import annotations

from app.core.exceptions import AppException


class AIConfigurationError(RuntimeError):
    """Raised when AI provider configuration is invalid or incomplete."""


class AIProviderUnavailableError(AppException):
    def __init__(self, message: str = "AI service is currently unavailable") -> None:
        super().__init__(
            message,
            status_code=503,
            error_code="AI_PROVIDER_UNAVAILABLE",
        )


class AIProviderTimeoutError(AppException):
    def __init__(self, message: str = "AI request exceeded execution time budget") -> None:
        super().__init__(
            message,
            status_code=504,
            error_code="AI_PROVIDER_TIMEOUT",
        )


class AIToolBudgetExceededError(AppException):
    def __init__(self, message: str = "AI tool execution budget exceeded") -> None:
        super().__init__(
            message,
            status_code=429,
            error_code="AI_TOOL_BUDGET_EXCEEDED",
        )


class AIToolValidationError(AppException):
    def __init__(self, message: str = "Invalid AI tool request") -> None:
        super().__init__(
            message,
            status_code=400,
            error_code="AI_TOOL_VALIDATION_ERROR",
        )


class AIConversationNotFoundError(AppException):
    def __init__(self, message: str = "AI conversation was not found") -> None:
        super().__init__(
            message,
            status_code=404,
            error_code="AI_CONVERSATION_NOT_FOUND",
        )


class AIConversationConflictError(AppException):
    def __init__(
        self,
        message: str = "AI conversation already has a turn in progress",
        *,
        error_code: str = "AI_CONVERSATION_CONFLICT",
    ) -> None:
        super().__init__(
            message,
            status_code=409,
            error_code=error_code,
        )


class AITurnInProgressError(AIConversationConflictError):
    def __init__(
        self,
        message: str = "AI turn is already in progress for this request key",
    ) -> None:
        super().__init__(message, error_code="AI_TURN_IN_PROGRESS")


class AIIdempotencyKeyReusedError(AIConversationConflictError):
    def __init__(
        self,
        message: str = "Idempotency key reused with a different request payload",
    ) -> None:
        super().__init__(message, error_code="AI_IDEMPOTENCY_KEY_REUSED")
