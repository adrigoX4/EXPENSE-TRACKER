from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details: Any = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message, details=details)


class ConflictError(AppError):
    status_code = 409
    code = "conflict"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None):
        super().__init__(message, code=code, details=details)


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message, details=details)
