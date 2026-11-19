from app.core.exceptions import ConflictException, ForbiddenError, NotFoundException


class EventNotFoundError(NotFoundException):
    def __init__(self) -> None:
        super().__init__("Event not found")
        self.error_code = "EVENT_NOT_FOUND"


class EventClubNotActiveError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Club is not active")
        self.error_code = "EVENT_CLUB_NOT_ACTIVE"


class EventInvalidStateError(ConflictException):
    def __init__(self, message: str = "Event state does not allow this action") -> None:
        super().__init__(message)
        self.error_code = "EVENT_INVALID_STATE"


class EventCapacityBelowRegistrationsError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Event capacity cannot be reduced below active registrations")
        self.error_code = "EVENT_CAPACITY_BELOW_REGISTRATIONS"


class EventCapacityFullError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Event has reached maximum capacity")
        self.error_code = "EVENT_CAPACITY_FULL"


class EventRegistrationWindowClosedError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Event registration window is closed")
        self.error_code = "EVENT_REGISTRATION_WINDOW_CLOSED"


class EventMembersOnlyError(ForbiddenError):
    def __init__(self) -> None:
        super().__init__("Active club membership is required for this event")
        self.error_code = "EVENT_MEMBERS_ONLY"


class DuplicateEventRegistrationError(ConflictException):
    def __init__(self) -> None:
        super().__init__("You are already registered for this event")
        self.error_code = "DUPLICATE_EVENT_REGISTRATION"


class EventRegistrationNotFoundError(NotFoundException):
    def __init__(self) -> None:
        super().__init__("Active event registration not found")
        self.error_code = "EVENT_REGISTRATION_NOT_FOUND"


class CancellationDeadlinePassedError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Cancellation deadline has passed")
        self.error_code = "CANCELLATION_DEADLINE_PASSED"
