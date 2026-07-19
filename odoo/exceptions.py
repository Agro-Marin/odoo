"""The Odoo Exceptions module defines a few core exception types.

Those types are understood by the RPC layer.
Any other exception type bubbling until the RPC layer will be
treated as a 'Server error'.
"""


class UserError(Exception):
    """Generic error managed by the client.

    Typically when the user tries to do something that has no sense given the current
    state of a record.
    """

    http_status = 422  # Unprocessable Entity

    def __init__(self, message: str) -> None:
        """
        :param message: exception message and frontend modal content
        """
        super().__init__(message)


class RedirectWarning(Exception):
    """Warning with a possibility to redirect the user instead of simply
    displaying the warning message.

    :param str message: exception message and frontend modal content
    :param action: the action to redirect to -- its database id (int) or its
        xml id (str)
    :type action: int | str
    :param str button_text: text to put on the button that will trigger
        the redirection.
    :param dict additional_context: context passed to the redirection action.
           Can be used to limit a view to active_ids for example.
    """

    def __init__(
        self,
        message: str,
        action: int | str,
        button_text: str,
        additional_context: dict | None = None,
    ) -> None:
        super().__init__(message, action, button_text, additional_context)


class AccessDenied(UserError):
    """Login/password error.

    .. note::

        Traceback only visible in the logs.

    .. admonition:: Example

        When you try to log with a wrong password.
    """

    http_status = 403  # Forbidden

    def __init__(self, message: str = "Access Denied") -> None:
        super().__init__(message)
        self.suppress_traceback()  # must be called in `except`s too

    def suppress_traceback(self) -> None:
        """
        Remove the traceback, cause and context of the exception, hiding
        where the exception occurred but keeping the exception message.

        This method must be called in all situations where we are about
        to print this exception to the users.

        It is OK to leave the traceback (thus to *not* call this method)
        if the exception is only logged in the logs, as they are only
        accessible by the system administrators.
        """
        self.with_traceback(None)
        self.traceback = ("", "", "")

        # During handling of the above exception, another exception occurred
        self.__context__ = None

        # The above exception was the direct cause of the following exception
        self.__cause__ = None


class AccessError(UserError):
    """Access rights error.

    .. admonition:: Example

        When you try to read a record that you are not allowed to.
    """

    http_status = 403  # Forbidden


class CacheMiss(KeyError):
    """Missing value(s) in cache.

    .. admonition:: Example

        When you try to read a value in a flushed cache.
    """

    def __init__(self, record: object, field: object) -> None:
        super().__init__("%r.%s" % (record, field.name))


class MissingError(UserError):
    """Missing record(s).

    .. admonition:: Example

        When you try to write on a deleted record.
    """

    http_status = 404  # Not Found


class LockError(UserError):
    """Record(s) could not be locked.

    .. admonition:: Example

        Code tried to lock records, but could not succeed.
    """

    http_status = 409  # Conflict


class ValidationError(UserError):
    """Violation of python constraints.

    .. admonition:: Example

        When you try to create a new user with a login which already exists in the db.
    """


class ConcurrencyError(Exception):
    """
    Signal that two concurrent transactions tried to commit something
    that violates some constraint. Signal that the transaction that
    failed should be retried after a short delay, see
    :func:`~odoo.service.transaction.retrying`.

    This exception is low-level and has very few use cases, it should
    only be used if all alternatives are deemed worse.
    """


class RetryableJobError(Exception):
    """Raised inside a background job (model ``ir.job``) to request a retry.

    The job's transaction is rolled back and the job is rescheduled — after
    ``seconds`` when given, else after the default exponential backoff — until
    its ``max_retries`` budget is exhausted, at which point it is marked
    ``failed`` like any other exception.

    .. admonition:: Example

        A job hit a transient condition (remote endpoint down, record locked
        by a concurrent transaction) that a later attempt should not hit.
    """

    def __init__(self, message: str = "", seconds: int | None = None) -> None:
        super().__init__(message)
        self.seconds = seconds
