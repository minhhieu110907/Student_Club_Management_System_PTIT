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


class ClubNotFoundError(NotFoundException):
    def __init__(self) -> None:
        super().__init__("Club not found")
        self.error_code = "CLUB_NOT_FOUND"


class ClubNotEligibleError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Club is not accepting membership applications")
        self.error_code = "CLUB_NOT_ELIGIBLE"


class ActiveMembershipExistsError(ConflictException):
    def __init__(self) -> None:
        super().__init__("An active membership already exists for this club")
        self.error_code = "ACTIVE_MEMBERSHIP_EXISTS"


class PendingMembershipApplicationError(ConflictException):
    def __init__(self) -> None:
        super().__init__("A membership application is already pending for this club")
        self.error_code = "MEMBERSHIP_APPLICATION_PENDING"


class RemovedMembershipReapplicationError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Reapplication after removal is not supported")
        self.error_code = "REMOVED_MEMBERSHIP_REAPPLICATION_DENIED"


class MembershipApplicationNotFoundError(NotFoundException):
    def __init__(self) -> None:
        super().__init__("Membership application not found")
        self.error_code = "MEMBERSHIP_APPLICATION_NOT_FOUND"


class MembershipApplicationAlreadyReviewedError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Membership application has already been reviewed")
        self.error_code = "MEMBERSHIP_APPLICATION_ALREADY_REVIEWED"


class ClubManagerRequiredError(ForbiddenError):
    def __init__(self) -> None:
        super().__init__("An active Manager membership is required")
        self.error_code = "CLUB_MANAGER_REQUIRED"


class MembershipNotFoundError(NotFoundException):
    def __init__(self) -> None:
        super().__init__("Membership not found")
        self.error_code = "MEMBERSHIP_NOT_FOUND"


class MembershipNotActiveError(ConflictException):
    def __init__(self) -> None:
        super().__init__("Membership is not active")
        self.error_code = "MEMBERSHIP_NOT_ACTIVE"


class ManagerLeaveNotAllowedError(ConflictException):
    def __init__(self) -> None:
        super().__init__("The final active manager cannot leave an active club")
        self.error_code = "MANAGER_LEAVE_NOT_ALLOWED"
