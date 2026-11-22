from app.core.exceptions import ConflictException, ForbiddenError, NotFoundException


class TaskNotFoundError(NotFoundException):
    def __init__(self) -> None:
        super().__init__("Event task not found")
        self.error_code = "TASK_NOT_FOUND"


class TaskAccessDeniedError(ForbiddenError):
    def __init__(self) -> None:
        super().__init__("You do not have permission to access or update this task")
        self.error_code = "TASK_ACCESS_DENIED"


class TaskEventNotEditableError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Tasks cannot be modified for cancelled or completed events")
        self.error_code = "TASK_EVENT_NOT_EDITABLE"


class InvalidTaskAssigneeError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Assignee must be an active member of the organizing club")
        self.error_code = "INVALID_TASK_ASSIGNEE"
