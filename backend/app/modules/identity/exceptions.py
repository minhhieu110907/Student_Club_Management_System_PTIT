from app.core.exceptions import AppException


class EmailAlreadyRegisteredError(AppException):
    def __init__(self) -> None:
        super().__init__(
            "Email is already registered",
            status_code=409,
            error_code="EMAIL_ALREADY_REGISTERED",
        )


class InvalidCredentialsError(AppException):
    def __init__(self) -> None:
        super().__init__(
            "Invalid email or password",
            status_code=401,
            error_code="INVALID_CREDENTIALS",
            headers={"WWW-Authenticate": "Bearer"},
        )


class OriginNotAllowedError(AppException):
    def __init__(self) -> None:
        super().__init__(
            "Origin is not allowed",
            status_code=403,
            error_code="ORIGIN_NOT_ALLOWED",
        )
