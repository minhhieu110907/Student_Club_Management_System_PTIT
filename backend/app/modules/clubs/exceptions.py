from app.core.exceptions import ConflictException, ForbiddenError, NotFoundException


class StudentRoleRequiredError(ForbiddenError):
    def __init__(self) -> None:
        super().__init__("Student role required")
        self.error_code = "STUDENT_ROLE_REQUIRED"


class AdminRoleRequiredError(ForbiddenError):
    def __init__(self) -> None:
        super().__init__("System administrator role required")
        self.error_code = "ADMIN_ROLE_REQUIRED"


class ClubRequestNotFoundError(NotFoundException):
    def __init__(self) -> None:
        super().__init__("Club creation request not found")
        self.error_code = "CLUB_REQUEST_NOT_FOUND"


class ClubRequestAlreadyReviewedError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Club creation request has already been reviewed")
        self.error_code = "CLUB_REQUEST_ALREADY_REVIEWED"


class RejectionReasonRequiredError(ConflictException):
    def __init__(self) -> None:
        super().__init__("A rejection reason is required")
        self.error_code = "REJECTION_REASON_REQUIRED"
