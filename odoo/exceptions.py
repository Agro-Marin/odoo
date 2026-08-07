__all__ = [
    "AccessDenied",
    "AccessError",
    "CacheMiss",
    "ConcurrencyError",
    "LockError",
    "MissingError",
    "RedirectWarning",
    "RetryableJobError",
    "TerminalJobError",
    "UserError",
    "ValidationError",
]


class UserError(Exception):
    http_status = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)


class RedirectWarning(Exception):
    def __init__(
        self,
        message: str,
        action: int | str,
        button_text: str,
        additional_context: dict | None = None,
    ) -> None:
        super().__init__(message, action, button_text, additional_context)


class AccessDenied(UserError):
    http_status = 403

    def __init__(self, message: str = "Access Denied") -> None:
        super().__init__(message)
        self.suppress_traceback()

    def suppress_traceback(self) -> None:
        self.with_traceback(None)
        self.traceback = ("", "", "")

        self.__context__ = None

        self.__cause__ = None


class AccessError(UserError):
    http_status = 403


class CacheMiss(KeyError):
    def __init__(self, record: object, field: object) -> None:
        super().__init__("%r.%s" % (record, field.name))


class MissingError(UserError):
    http_status = 404


class LockError(UserError):
    http_status = 409


class ValidationError(UserError):
    pass


class ConcurrencyError(Exception):
    pass


class RetryableJobError(Exception):
    def __init__(self, message: str = "", seconds: int | None = None) -> None:
        super().__init__(message)
        self.seconds = seconds


class TerminalJobError(UserError):
    pass
