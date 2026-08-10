class CommError(Exception):
    """Base exception for all communication errors."""

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        self.code = code or "comm_error"
        super().__init__(message)


class AuthenticationError(CommError):
    """Authentication failed."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "auth_error")


class RateLimitError(CommError):
    """Rate limit exceeded."""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, "rate_limit_error")


class CommTimeoutError(CommError):
    """Request timed out."""

    def __init__(self, message: str = "Request timed out"):
        super().__init__(message, "timeout_error")


class ClientError(CommError):
    """Client-side error (4xx)."""

    def __init__(self, message: str = "Client error"):
        super().__init__(message, "client_error")


class ServerError(CommError):
    """Server-side error (5xx)."""

    def __init__(self, message: str = "Server error"):
        super().__init__(message, "server_error")


class ValidationError(CommError):
    """Payload validation error."""

    def __init__(self, message: str = "Validation error"):
        super().__init__(message, "validation_error")


class DuplicateEventError(CommError):
    """Duplicate event detected."""

    def __init__(self, message: str = "Duplicate event"):
        super().__init__(message, "duplicate_error")
