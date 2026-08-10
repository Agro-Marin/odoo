import logging
from typing import Any

from odoo import fields
from odoo.http import request

from .base_controller import BaseCommController, ValidationResult
from odoo.addons.api_transport.tools import (
    compute_payload_hash,
    validate_json_payload,
)

_logger = logging.getLogger(__name__)


class InboundController(BaseCommController):
    """Controller mixin for handling inbound API requests.

    Subclasses call :meth:`validate_inbound_request` from an ``@http.route``
    handler and return ``result.response`` when ``result.success`` is False.
    """

    def _get_identifier_field(self, endpoint_model: str) -> str:
        """Return the field name used to identify an endpoint (override in subclasses).

        :param endpoint_model: model name
        :return: the identifier field name
        :rtype: str
        """
        field_map = {
            "remote.device": "identifier",
        }
        return field_map.get(endpoint_model, "identifier")

    def _payload_too_large(self, endpoint: Any) -> ValidationResult:
        """Build the 413 result for an over-size request body."""
        _logger.warning(
            "Payload too large for endpoint %s (limit: %d bytes)",
            endpoint.display_name,
            endpoint.max_payload_size,
        )
        return ValidationResult(
            success=False,
            response=self._error_response(
                "payload_too_large",
                f"Request exceeds maximum size of {endpoint.max_payload_size // 1024}KB",
                413,
            ),
            error_message="Payload too large",
        )

    def validate_inbound_request(  # pylint: disable=too-many-return-statements
        self,
        endpoint_model: str,
        endpoint_identifier: str,
        endpoint_domain: list | None = None,
        require_json: bool = True,
        check_rate_limit: bool = True,
        check_duplicates: bool = True,
        create_event_log: bool = True,
    ) -> ValidationResult:
        """Run the inbound-request validation pipeline for an endpoint.

        The numbered steps below (endpoint lookup, size, IP, rate limit, auth,
        parse, log, duplicate) are annotated inline. IP and rate-limit checks run
        BEFORE auth so failed attempts are throttled and unauthorized sources
        never learn whether their credentials would have been accepted.

        :param endpoint_model: model name of the endpoint (e.g. 'remote.device')
        :param endpoint_identifier: identifier to find the endpoint
        :param endpoint_domain: additional search domain
        :param require_json: require a JSON payload (default True)
        :param check_rate_limit: enforce rate limiting (default True)
        :param check_duplicates: enforce duplicate detection (default True)
        :param create_event_log: create an api.event.log record (default True);
            set False when the endpoint has its own event model (e.g. webhook.event)
        :return: a ValidationResult with the endpoint, payload and event_log,
            or an error response
        :rtype: ValidationResult
        """
        start_time = fields.Datetime.now()
        remote_addr = self._get_remote_address()

        # Build search domain. Copy the caller's list rather than appending to
        # it: this used to mutate whatever list was passed in.
        identifier_field = self._get_identifier_field(endpoint_model)
        domain = [
            *(endpoint_domain or []),
            (identifier_field, "=", endpoint_identifier),
            ("active", "=", True),
        ]

        # 1. Find endpoint.
        #
        # The identifier is unique PER COMPANY (remote.device carries
        # UNIQUE(identifier, company_id)), so a plain limit=1 search could return
        # another company's device: its credential does not match, the legitimate
        # device gets a 401, and a tenant can deny service to another tenant's
        # hardware just by creating a device with the same identifier. Fetch every
        # candidate and let authentication pick the one that actually holds the
        # presented secret.
        candidates = request.env[endpoint_model].sudo().search(domain)
        endpoint = candidates[:1]

        if not endpoint:
            _logger.warning(
                "Endpoint not found: %s with %s=%s",
                endpoint_model,
                identifier_field,
                endpoint_identifier,
            )
            return ValidationResult(
                success=False,
                response=self._error_response(
                    "endpoint_not_found",
                    "Endpoint not found or inactive",
                    404,
                ),
                error_message="Endpoint not found",
            )

        # 2a. Cheap pre-read size reject on the declared Content-Length.
        content_length = request.httprequest.content_length
        if content_length and content_length > endpoint.max_payload_size:
            return self._payload_too_large(endpoint)

        # 3. Check IP whitelist (before auth: don't reveal auth outcome to
        #    unauthorized sources, and don't spend auth work on them).
        if endpoint.ip_whitelist and not endpoint.validate_ip_address(remote_addr):
            _logger.warning(
                "IP not allowed: %s for endpoint %s",
                remote_addr,
                endpoint.display_name,
            )
            return ValidationResult(
                success=False,
                response=self._error_response(
                    "ip_not_allowed",
                    "Your IP address is not authorized",
                    403,
                ),
                error_message=f"IP {remote_addr} not allowed",
            )

        # 4. Check rate limit (before auth: throttles credential/HMAC brute force).
        if (
            check_rate_limit
            and endpoint.rate_limit_enabled
            and not endpoint.check_rate_limit()
        ):
            _logger.warning(
                "Rate limit exceeded for endpoint %s",
                endpoint.display_name,
            )
            return ValidationResult(
                success=False,
                response=self._error_response(
                    "rate_limit_exceeded",
                    "Too many requests - please slow down",
                    429,
                ),
                error_message="Rate limit exceeded",
            )

        # 5. Read the body once (raw bytes), then enforce the real size. This
        #    catches chunked/streamed requests that omit Content-Length, where
        #    step 2a cannot fire.
        body_bytes = request.httprequest.get_data(as_text=False)
        if len(body_bytes) > endpoint.max_payload_size:
            return self._payload_too_large(endpoint)
        # Decode once for JSON parsing and storage; the signature is verified
        # against the raw bytes (below) so a non-UTF-8 body is not silently
        # mangled by errors="replace" before the HMAC is computed.
        body_str = body_bytes.decode("utf-8", errors="replace")

        # 6. Authenticate (HMAC is checked over the raw bytes).
        #
        # With more than one candidate sharing the identifier across companies,
        # the request belongs to whichever one its credential authenticates
        # against — checking only the first would hand a cross-tenant denial of
        # service to anyone able to create a device.
        headers = dict(request.httprequest.headers)
        is_authenticated = False
        last_error = None
        for candidate in candidates:
            # Per-candidate guard: a misconfigured endpoint (no credential for a
            # credential-based auth_type raises) must not stop a correctly
            # configured sibling from authenticating.
            try:
                if candidate.authenticate_request(headers=headers, body=body_bytes):
                    endpoint = candidate
                    is_authenticated = True
                    break
            except Exception as e:
                last_error = e
                _logger.exception(
                    "Authentication error for %s %s",
                    endpoint_model,
                    endpoint_identifier,
                )

        if not is_authenticated and last_error is not None and len(candidates) == 1:
            return ValidationResult(
                success=False,
                response=self._error_response(
                    "authentication_error",
                    "Authentication failed",
                    401,
                ),
                error_message=f"Authentication error: {last_error}",
            )

        if not is_authenticated:
            _logger.warning(
                "Authentication failed for %s %s",
                endpoint_model,
                endpoint_identifier,
            )
            return ValidationResult(
                success=False,
                response=self._error_response(
                    "authentication_failed",
                    "Invalid credentials",
                    401,
                ),
                error_message="Authentication failed",
            )

        # 7. Parse payload
        payload_dict = None
        payload_hash = None

        if require_json:
            is_valid, payload_dict, error = validate_json_payload(body_str)

            if not is_valid:
                _logger.warning("Invalid JSON payload: %s", error)
                return ValidationResult(
                    success=False,
                    response=self._error_response(
                        "invalid_json",
                        error,
                        400,
                    ),
                    error_message=error,
                )

            payload_hash = compute_payload_hash(payload_dict)

        # 8. Create event log (optional - skip if endpoint has its own event model)
        event_log = None
        if create_event_log:
            channel_ref = f"{endpoint._name},{endpoint.id}"
            event_log = (
                request.env["api.event.log"]
                .sudo()
                .create(
                    {
                        "direction": "inbound",
                        "channel_id": channel_ref,
                        "request_payload": body_str,
                        "source_ip": remote_addr,
                        "state": "pending",
                    },
                )
            )

        # 9. Check for duplicates (only if event_log was created)
        if (
            check_duplicates
            and endpoint.duplicate_detection_enabled
            and payload_hash
            and event_log
        ):
            if endpoint.check_duplicate_event(
                payload_hash, exclude_event_id=event_log.id
            ):
                _logger.info(
                    "Duplicate event detected for endpoint %s (event %d)",
                    endpoint.display_name,
                    event_log.id,
                )

                event_log.mark_duplicate()

                return ValidationResult(
                    success=False,
                    response=self._error_response(
                        "duplicate_event",
                        "Duplicate event detected",
                        409,
                    ),
                    error_message="Duplicate event",
                )

        # All validation passed!
        duration = (fields.Datetime.now() - start_time).total_seconds()
        _logger.debug(
            "Request validated in %.3fs for %s",
            duration,
            endpoint.display_name,
        )

        return ValidationResult(
            success=True,
            endpoint=endpoint,
            payload=payload_dict,
            payload_hash=payload_hash,
            event_log=event_log,
        )
