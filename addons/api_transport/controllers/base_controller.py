import json
import logging
from dataclasses import dataclass
from typing import Any

from odoo.http import Response, request

_logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of inbound request validation."""

    success: bool
    endpoint: Any | None = None
    payload: dict[str, Any] | None = None
    payload_hash: str | None = None
    event_log: Any | None = None
    response: Response | None = None
    error_message: str | None = None


class BaseCommController:
    """Base controller with common utilities for API communications."""

    def _error_response(self, error_code: str, message: str, status: int) -> Response:
        """Create a standardized error response.

        :param error_code: machine-readable error code
        :param message: human-readable error message
        :param status: HTTP status code
        :return: the HTTP response
        :rtype: odoo.http.Response
        """
        return self._json_response(
            {"error": error_code, "message": message},
            status=status,
        )

    def _get_remote_address(self) -> str:
        """Return the trusted remote IP address for the request.

        :return: the client IP, or "unknown"
        :rtype: str
        """
        # Never trust a client-supplied X-Forwarded-For header: reading it would
        # let any caller spoof its source IP, bypass endpoint IP allowlists and
        # poison the audit trail. Behind a proxy the deployment sets proxy_mode,
        # which installs werkzeug's ProxyFix to rewrite remote_addr from the
        # trusted forwarded chain — so we rely solely on remote_addr.
        if request.httprequest:
            return request.httprequest.remote_addr or "unknown"
        return "unknown"

    def _json_response(self, data: dict, status: int = 200) -> Response:
        """Create a JSON response with security headers.

        :param data: response data
        :param status: HTTP status code (default 200)
        :return: the HTTP response
        :rtype: odoo.http.Response
        """
        return Response(
            json.dumps(data),
            status=status,
            mimetype="application/json",
            headers={
                "Content-Type": "application/json",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Cache-Control": "no-store, no-cache, must-revalidate, private",
                "Pragma": "no-cache",
            },
        )

    def _log_request(
        self,
        endpoint: Any,
        success: bool,
        message: str,
        duration: float | None = None,
        error: str | None = None,
    ) -> None:
        """Log the request in a structured format.

        :param endpoint: endpoint record
        :param success: whether the request succeeded
        :param message: status message
        :param duration: request duration in seconds
        :param error: error message if failed
        """
        level = logging.INFO if success else logging.ERROR
        status = "SUCCESS" if success else "FAILURE"

        _logger.log(
            level,
            "COMM_REQUEST_%s endpoint=%s model=%s duration=%.3fs message='%s' error='%s'",
            status,
            endpoint.display_name if endpoint else "unknown",
            endpoint._name if endpoint else "unknown",
            duration or 0.0,
            message,
            error or "",
        )
