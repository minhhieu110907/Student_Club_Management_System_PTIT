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
    def __init__(self, message: str = "AI conversation already has a turn in progress") -> None:
        super().__init__(
            message,
            status_code=409,
            error_code="AI_CONVERSATION_CONFLICT",
        )
