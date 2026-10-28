from app.core.exceptions import AppException


class EmailAlreadyRegisteredError(AppException):
    def __init__(self) -> None:
        super().__init__(
            "Email is already registered",
            status_code=409,
            error_code="EMAIL_ALREADY_REGISTERED",
        )
