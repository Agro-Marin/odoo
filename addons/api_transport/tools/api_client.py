import ipaddress
import json
import logging
import re
import uuid
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from odoo import _, fields
from odoo.exceptions import UserError

from .exceptions import (
    AuthenticationError,
    ClientError,
    CommError,
    CommTimeoutError,
    RateLimitError,
    ServerError,
)
from .payload import split_large_payload
from odoo.addons.base_credential_manager.tools import (
    EndpointRateLimiter as RateLimiter,
)
from odoo.addons.base_credential_manager.tools.session_cache import (
    get_session_cache,
)

_logger = logging.getLogger(__name__)

# Pattern to match Telegram bot tokens in URLs
# Format: /bot<BOT_ID>:<SECRET>/ or end of URL
_TELEGRAM_TOKEN_PATTERN = re.compile(r"/bot(\d+):([A-Za-z0-9_-]+)(/|$)")

# Services that carry their API version through a dedicated auth header
# (or expect none), so the generic API-Version / X-API-Version headers must
# NOT be added for them (see APIGatewayClient._build_headers).
_SELF_VERSIONED_SERVICES = frozenset({"claude", "gemini"})

# Sensitive field patterns (case-insensitive). Shared between payload redaction
# and URL query-string redaction so both paths mask the same vocabulary.
_SENSITIVE_FIELD_PATTERNS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "privatekey",
    "credential",
    "auth",
    "bearer",
    "signature",
    "x-amz-security-token",
    "x-amz-signature",
)

# Ceiling on a single payload stored in api.event.log, request or response.
# The rows are an audit trail, not a body archive.
_MAX_LOGGED_PAYLOAD = 10000


def _mask_sensitive_url(url: str) -> str:
    """Mask sensitive data in a URL for safe logging.

    Masks Telegram bot tokens (keeping a short tail), URL userinfo, and
    sensitive query params (token, secret, api_key, authorization, …).

    :param url: the URL to mask
    :return: the URL with sensitive parts masked, or the original if unparseable
    :rtype: str
    """

    def mask_telegram_token(match):
        bot_id = match.group(1)
        secret = match.group(2)
        suffix = match.group(3)
        if len(secret) > 4:
            masked = f"/bot{bot_id}:***...{secret[-4:]}{suffix}"
        else:
            masked = f"/bot{bot_id}:****{suffix}"
        return masked

    # Step 1: Telegram-specific token masking (keeps tail for debugging)
    masked = _TELEGRAM_TOKEN_PATTERN.sub(mask_telegram_token, url)

    # Step 2: generic URL masking (userinfo + sensitive query params)
    try:
        parsed = urlparse(masked)
    except ValueError:
        return masked

    netloc = parsed.netloc
    if "@" in netloc:
        # Drop userinfo (user:password@host:port) entirely from the log
        host_part = netloc.rsplit("@", 1)[1]
        netloc = f"***:***@{host_part}"

    query = parsed.query
    if query:
        redacted_pairs = []
        for key, value in parse_qsl(query, keep_blank_values=True):
            if any(p in key.lower() for p in _SENSITIVE_FIELD_PATTERNS):
                redacted_pairs.append((key, "***REDACTED***"))
            else:
                redacted_pairs.append((key, value))
        query = urlencode(redacted_pairs)

    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, query, parsed.fragment),
    )


# ==================== Payload Splitting (Pattern: bus module) ====================




# ==================== Main API Client ====================


class APIGatewayClient:
    """HTTP transport client for outbound services (retries, caching, auth, rate limiting, redacted logging)."""

    def __init__(self, env, service_code, company_id=None, credential_id=None):
        self.env = env
        self.service_code = service_code
        self.company_id = company_id or env.company.id
        self.user_id = env.user.id

        # Load service configuration
        self.service = (
            env["api.endpoint.outbound"]
            .sudo()
            .search(
                [
                    ("code", "=", service_code),
                    ("active", "=", True),
                ],
                limit=1,
            )
        )

        if not self.service:
            raise CommError(
                _("API service '%s' not found or inactive") % service_code,
            )

        # Load credentials
        if credential_id:
            self.credential = env["credential.credential"].sudo().browse(credential_id)
            if not self.credential.exists() or not self.credential.active:
                raise CommError(_("Invalid or inactive credential"))
        else:
            self.credential = (
                env["credential.credential"]
                .sudo()
                .search(
                    [
                        ("service_id", "=", self.service.id),
                        ("company_id", "=", self.company_id),
                        ("active", "=", True),
                    ],
                    order="sequence, id",
                    limit=1,
                )
            )

        # A service declaring auth_type 'none' has nothing to authenticate with,
        # and demanding a credential anyway is what kept unauthenticated
        # integrations off this transport entirely -- they went back to bare
        # requests calls rather than invent an empty credential record.
        if not self.credential and self.service.auth_type != "none":
            raise CommError(
                _(
                    "No active credentials for service '%(service)s' and company ID %(company)s",
                    service=service_code,
                    company=self.company_id,
                ),
            )

        # Check if credential is expired
        if self.credential.is_expired:
            raise CommError(
                _("Credentials have expired on %s") % self.credential.date_expiration,
            )

        # Initialize session
        self.session = self._get_or_create_session()

        # Base URL. The credential's environment wins where there is one; an
        # unauthenticated service has only its own, and falling through to the
        # test URL because an absent credential is not "production" would send
        # live traffic somewhere harmless-looking and wrong.
        environment = self.credential.environment if self.credential else self.service.environment
        if environment == "production":
            self.base_url = self.service.endpoint_url
        else:
            self.base_url = self.service.endpoint_url_test or self.service.endpoint_url

        # Initialize rate limiter (FIX HIGH-2: database-backed token bucket)
        self.rate_limiter = RateLimiter(
            env,
            self.service,
            self.company_id,
        )

        _logger.info(
            "APIGatewayClient initialized: service=%s, company=%s, environment=%s",
            service_code,
            self.company_id,
            self.credential.environment,
        )

    def _get_or_create_session(self):
        """Get cached session or create new one.

        Uses registry-based cache for proper lifecycle management and automatic
        invalidation on module upgrades.
        """
        # Get cache and generate key
        cache = get_session_cache(self.env)
        cache_key = (
            f"{self.service_code}:{self.company_id}:{self.credential.credential_hash}"
        )

        # Try to get cached session
        session = cache.get(cache_key)

        if session is None:
            # Create new session and cache it
            session = self._create_session()
            cache.set(cache_key, session)

        return session

    def _create_session(self):
        """Create new requests session with connection pooling and retries"""
        session = requests.Session()

        # Configure connection pooling
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=50,
            max_retries=(self._get_retry_config() if self.service.retry_enabled else 0),
        )

        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set default headers
        session.headers.update(
            {
                "User-Agent": f"Odoo-API-Gateway/1.0 ({self.service_code})",
                "Accept": "application/json",
            },
        )

        _logger.debug("Created new session for %s", self.service_code)

        return session

    def _get_retry_config(self):
        """Get retry configuration"""
        if not self.service.retry_enabled:
            return None

        backoff_factor = {
            "fixed": 1.0,
            "linear": 1.0,
            "exponential": 2.0,
        }.get(self.service.retry_backoff_type, 2.0)

        return Retry(
            total=self.service.retry_max_attempts or 3,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        )

    def request(self, method, endpoint, raw=False, **kwargs):
        """Make HTTP request to the API.

        :param raw: When True, return the live ``requests.Response`` object
            WITHOUT parsing or consuming the body. This is required for
            streaming callers (they iterate ``response.iter_lines()`` /
            ``iter_content()`` themselves). Rate limiting, retries (via the
            session adapter), authentication and headers all still apply.
            When False (default) the body is parsed and a dict is returned.
        """
        method = method.upper()
        trace_id = kwargs.pop("trace_id", str(uuid.uuid4()))
        skip_cache = kwargs.pop("skip_cache", False)
        skip_rate_limit = kwargs.pop("skip_rate_limit", False)
        skip_logging = kwargs.pop("skip_logging", False)

        url = self._build_url(endpoint)

        # Check cache - failures shouldn't break the API call
        if method == "GET" and not skip_cache and self.service.cache_enabled:
            try:
                cached = self._get_from_cache(url, kwargs.get("params"))
                if cached:
                    if not skip_logging:
                        self._log_request(
                            method,
                            url,
                            kwargs,
                            cached,
                            trace_id,
                            cache_hit=True,
                        )
                    return cached
            except Exception as cache_error:
                # Log cache errors but continue with the API call
                _logger.warning(
                    "Failed to retrieve from cache, proceeding with API call: %s",
                    cache_error,
                    exc_info=True,
                )
                # Track cache failures for monitoring
                self._increment_cache_error()

        # Check rate limit
        if not skip_rate_limit and self.service.rate_limit_enabled:
            if not self.rate_limiter.check_limit():
                raise RateLimitError(
                    _("Rate limit exceeded for service '%s'. Please try again later.")
                    % self.service_code,
                )

        # Prepare request
        headers = self._build_headers(kwargs.pop("headers", {}))
        auth = self._get_auth()

        # Set timeout
        if "timeout" not in kwargs:
            kwargs["timeout"] = (
                self.service.timeout_connect or 10,
                self.service.timeout_read or 30,
            )

        # Make request
        start_time = datetime.now()
        response_data = None
        error = None

        try:
            _logger.info("API Request: %s %s", method, _mask_sensitive_url(url))

            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                auth=auth,
                **kwargs,
            )

            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

            response.raise_for_status()

            # Streaming / raw passthrough: hand the live Response back to the
            # caller without consuming or parsing the body. Used by the AI
            # clients' streaming_* methods, which iterate the response
            # themselves. The body must not be touched here.
            if raw:
                self._track_usage(True)
                if not skip_logging:
                    self._log_request(method, url, kwargs, None, trace_id)
                return response

            response_data = self._parse_response(response, elapsed_ms)

            # Cache response - failures shouldn't break the API call
            if (
                method == "GET"
                and response.status_code == 200
                and self.service.cache_enabled
            ):
                try:
                    self._save_to_cache(url, kwargs.get("params"), response_data)
                except Exception as cache_error:
                    # Log cache errors but don't fail the API call
                    _logger.warning(
                        "Failed to save response to cache: %s",
                        cache_error,
                        exc_info=True,
                    )
                    # Track cache failures for monitoring
                    self._increment_cache_error()

            # Update credential usage
            self._track_usage(True)

            # Log request
            if not skip_logging:
                self._log_request(method, url, kwargs, response_data, trace_id)

            return response_data

        except requests.exceptions.Timeout as e:
            error = str(e)
            _logger.error("API Timeout: %s - %s", url, error)
            self._track_usage(False)

            if not skip_logging:
                self._log_request(
                    method,
                    url,
                    kwargs,
                    None,
                    trace_id,
                    error=error,
                    error_type="timeout",
                )

            raise CommTimeoutError(_("Request timed out: %s") % url) from e

        except requests.exceptions.HTTPError as e:
            error = self._extract_error(e.response)
            _logger.error("API HTTP Error: %s - %s", url, error)
            self._track_usage(False)

            # Map HTTP status into the ``api.event.log.error_type``
            # selection (network/timeout/auth/validation/rate_limit/
            # server/duplicate/other).  The historical ``"http"`` value
            # was not in the selection and broke the precommit batch
            # insert (ValueError → whole transaction rolled back).
            status_code = e.response.status_code
            if status_code == 401:
                event_error_type = "auth"
            elif status_code == 429:
                event_error_type = "rate_limit"
            elif 400 <= status_code < 500:
                event_error_type = "validation"
            else:
                event_error_type = "server"

            # Persist the HTTP status code on the audit row so dashboards
            # can filter / count by status — earlier ``response_data=None``
            # left ``status_code`` at 0 for every 4xx/5xx outcome.
            error_response = {
                "status_code": status_code,
                "headers": dict(e.response.headers or {}),
                "body": None,
            }

            if not skip_logging:
                self._log_request(
                    method,
                    url,
                    kwargs,
                    error_response,
                    trace_id,
                    error=error,
                    error_type=event_error_type,
                )

            if status_code == 401:
                raise AuthenticationError(_("Authentication failed: %s") % error) from e
            if status_code == 429:
                raise RateLimitError(_("Rate limit exceeded: %s") % error) from e
            if 400 <= status_code < 500:
                raise ClientError(_("Client error: %s") % error) from e
            raise ServerError(_("Server error: %s") % error) from e

        except requests.exceptions.RequestException as e:
            error = str(e)
            _logger.error("API Request Error: %s - %s", url, error)
            self._track_usage(False)

            if not skip_logging:
                self._log_request(
                    method,
                    url,
                    kwargs,
                    None,
                    trace_id,
                    error=error,
                    error_type="network",
                )

            raise CommError(_("Request failed: %s") % error) from e

        except Exception as e:
            error = str(e)
            _logger.exception("Unexpected API error")
            self._track_usage(False)

            if not skip_logging:
                self._log_request(
                    method,
                    url,
                    kwargs,
                    None,
                    trace_id,
                    error=error,
                    error_type="other",
                )

            raise CommError(_("Unexpected error: %s") % error) from e

    def get(self, endpoint, **kwargs):
        """Convenience method for GET requests"""
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint, **kwargs):
        """Convenience method for POST requests"""
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint, **kwargs):
        """Convenience method for PUT requests"""
        return self.request("PUT", endpoint, **kwargs)

    def patch(self, endpoint, **kwargs):
        """Convenience method for PATCH requests"""
        return self.request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint, **kwargs):
        """Convenience method for DELETE requests"""
        return self.request("DELETE", endpoint, **kwargs)

    def post_bulk(self, endpoint, items, max_payload_size=None, **kwargs):
        """POST bulk data, splitting large payloads that exceed API size limits.

        :param endpoint: API endpoint
        :param items: list of items to send
        :param max_payload_size: maximum payload size in bytes (default 1MB)
        :param kwargs: additional request parameters
        :return: one response dict per chunk
        :rtype: list
        """
        if not isinstance(items, list):
            raise ClientError("post_bulk requires a list of items")

        # Use service-specific max payload size or default
        max_size = max_payload_size or (1024 * 1024)  # 1MB default

        # Split into chunks that fit within API limits
        chunks = split_large_payload(items, max_size=max_size)

        if len(chunks) > 1:
            _logger.info(
                "Payload split into %d chunks for %s (max size: %d bytes)",
                len(chunks),
                endpoint,
                max_size,
            )

        # Send each chunk and collect responses. Always return a list (one
        # response per chunk) so callers never have to type-sniff on chunk count.
        responses = []
        for i, chunk in enumerate(chunks, 1):
            _logger.debug(
                "Sending chunk %d/%d with %d items to %s",
                i,
                len(chunks),
                len(chunk) if isinstance(chunk, list) else 1,
                endpoint,
            )

            # Merge kwargs with json parameter for the chunk
            chunk_kwargs = kwargs.copy()
            chunk_kwargs["json"] = chunk

            response = self.post(endpoint, **chunk_kwargs)
            responses.append(response)

        return responses

    def _build_url(self, endpoint):
        """Build the full URL from ``base_url`` and an endpoint path.

        The endpoint may be absolute (returned as-is) or relative, with or
        without a leading slash; the base may or may not carry a path segment.

        :param endpoint: API endpoint path
        :return: full URL
        :rtype: str
        :raises ValueError: if base_url format is invalid
        """
        # If endpoint is already a full URL, return as-is
        if endpoint.startswith(("http://", "https://")):
            return endpoint

        # Validate with urllib.parse rather than a regex — it parses scheme and
        # hostname reliably instead of pattern-matching.
        try:
            parsed = urlparse(self.base_url)

            # Validate scheme
            if parsed.scheme not in ("http", "https"):
                raise ValueError(
                    f"Invalid URL scheme '{parsed.scheme}' for service '{self.service_code}'. "
                    f"Expected 'http' or 'https'.",
                )

            # Validate hostname exists
            if not parsed.netloc:
                raise ValueError(
                    f"Missing hostname in base URL for service '{self.service_code}': {self.base_url}"
                )

            # Validate port if specified
            if parsed.port is not None:
                if not (0 < parsed.port <= 65535):
                    raise ValueError(
                        f"Invalid port {parsed.port} in base URL for service '{self.service_code}'. "
                        f"Port must be between 1 and 65535.",
                    )

            # Validate IP address format if it looks like an IP
            hostname = parsed.hostname or parsed.netloc.split(":")[0]
            if hostname not in ("localhost", "127.0.0.1"):
                # Check if it looks like an IP address
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", hostname):
                    try:
                        # Validate IP address format
                        ipaddress.ip_address(hostname)
                    except ValueError as e:
                        raise ValueError(
                            f"Invalid IP address '{hostname}' in base URL for service '{self.service_code}': {e}",
                        ) from e

        except ValueError as e:
            # Re-raise ValueError with context
            raise ValueError(
                f"Invalid base URL format for service '{self.service_code}': {self.base_url}\n"
                f"Error: {e}\n"
                f"Expected format: https://api.example.com or https://api.example.com/v1",
            ) from e

        # Normalize: remove trailing slash from base, leading slash from endpoint
        base = self.base_url.rstrip("/")
        endpoint_normalized = endpoint.lstrip("/")

        # Build full URL
        if endpoint_normalized:
            full_url = f"{base}/{endpoint_normalized}"
        else:
            full_url = base

        _logger.debug(
            "Built URL: %s (base: %s, endpoint: %s)",
            full_url,
            self.base_url,
            endpoint,
        )

        return full_url

    def _build_headers(self, additional_headers=None):
        """Build request headers with authentication"""
        headers = self.credential.get_auth_headers() if self.credential else {}

        # The generic ``API-Version`` / ``X-API-Version`` headers are only
        # meaningful for services that use that convention. Providers that
        # carry their version through a dedicated header (e.g. Claude's
        # ``anthropic-version``, injected by get_auth_headers) or that expect
        # no version header at all (Gemini) are excluded so we don't emit a
        # bogus ``API-Version: v1beta``.
        if (
            self.service.api_version
            and self.service.code not in _SELF_VERSIONED_SERVICES
        ):
            headers.setdefault("API-Version", self.service.api_version)
            headers.setdefault("X-API-Version", self.service.api_version)

        if additional_headers:
            headers.update(additional_headers)

        return headers

    def _get_auth(self):
        """Get authentication tuple for basic auth"""
        return self.credential.get_basic_auth() if self.credential else None

    def _parse_response(self, response, elapsed_ms):
        """Parse HTTP response into standardized dict"""
        try:
            # Try to parse as JSON
            body = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            # If JSON parsing fails, use text content
            _logger.debug("Response is not JSON: %s. Using text content.", e)
            body = response.text

            # If text is empty, return a simple success indicator
            if not body and response.status_code < 300:
                body = {"status": "ok", "message": "Request successful"}

        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "text": response.text,
            "elapsed_ms": elapsed_ms,
            "from_cache": False,
        }

    def _extract_error(self, response):
        """Extract error message from failed response"""
        try:
            error_data = response.json()
            for field in ["error", "message", "error_description", "detail"]:
                if field in error_data:
                    error_value = error_data[field]
                    if isinstance(error_value, dict) and "message" in error_value:
                        return error_value["message"]
                    return str(error_value)
            return json.dumps(error_data)
        except Exception as e:
            # Fallback to response text if JSON parsing/processing fails
            _logger.debug("Could not extract error from JSON: %s", e)
            return response.text[:500]

    def _get_from_cache(self, url, params):
        """Retrieve response from cache using api_communication's cache model."""
        cache_model = self.env["comm.response.cache"].sudo()
        return cache_model.get_cached_response(
            service_code=self.service_code,
            url=url,
            params=params,
            company_id=self.company_id,
        )

    def _save_to_cache(self, url, params, response_data):
        """Save response to cache using api_communication's cache model."""
        cache_model = self.env["comm.response.cache"].sudo()
        cache_model.set_cached_response(
            service_code=self.service_code,
            url=url,
            response=response_data,
            params=params,
            company_id=self.company_id,
        )

    def _increment_cache_error(self):
        """Increment cache error counter for monitoring.

        Tracks cache failures to provide health visibility.
        Runs with sudo() to avoid permission issues during API calls.
        """
        try:
            self.service.sudo().write(
                {
                    "cache_error_count": self.service.cache_error_count + 1,
                    "cache_last_error": fields.Datetime.now(),
                },
            )
        except Exception as e:
            # Don't let error tracking break the API call
            _logger.debug("Failed to increment cache error counter: %s", e)

    def _ensure_log_hooks(self):
        """Setup precommit hooks for batch logging.

        Pattern from bus module (bus.py:132-165): Use precommit hooks
        for transactional safety and batch inserts.

        Benefits:
        - Batch insert (10-100x faster than individual creates)
        - Transactional safety (logs only created if transaction succeeds)
        """
        if "api.event.log.values" not in self.env.cr.precommit.data:
            self.env.cr.precommit.data["api.event.log.values"] = []

            @self.env.cr.precommit.add
            def batch_create_logs():
                """Batch insert all queued logs in one query"""
                logs = self.env.cr.precommit.data.pop("api.event.log.values")
                if logs:
                    self.env["api.event.log"].sudo().create(logs)
                    _logger.debug("Batch created %d API event logs", len(logs))

    def _log_request(
        self,
        method,
        url,
        request_kwargs,
        response_data,
        trace_id,
        cache_hit=False,
        error=None,
        error_type=None,
    ):
        """Log API request/response with batch insert.

        Uses api.event.log from api_communication module with direction='outbound'.
        Pattern from bus module: Queue log in precommit for batch creation.

        Never raises. This runs *after* the exchange has already happened, so a
        failure here cannot undo the call it is describing -- and letting one
        escape would surface as a failure of the request itself. It previously
        did: a ``data=`` body reached ``json.dumps`` unserialized, the TypeError
        was caught by ``request``'s bare ``except Exception``, the successful
        call was counted against the credential, and the retry from that handler
        raised the same TypeError again with nothing left to catch it. A logging
        problem belongs in the server log.
        """
        try:
            self._queue_event_log(
                method,
                url,
                request_kwargs,
                response_data,
                trace_id,
                cache_hit=cache_hit,
                error=error,
                error_type=error_type,
            )
        except Exception:
            _logger.exception(
                "Could not record an api.event.log row for %s %s (trace %s); "
                "the exchange itself is unaffected.",
                method,
                _mask_sensitive_url(url),
                trace_id,
            )

    def _track_usage(self, success):
        """Record the outcome against the credential, if there is one.

        A service declaring ``auth_type = 'none'`` carries no credential, so
        ``self.credential`` is an empty recordset and ``increment_usage``'s
        ``ensure_one`` rejects it. That is bookkeeping raising on the way out of
        a call that already succeeded -- and, being inside ``request``'s bare
        ``except Exception``, it took the same double-fault route the payload
        serializer did: the handler called this again and the second failure had
        nothing left to catch it. Every unauthenticated service was affected on
        its success path, which is every call any of them ever makes.

        :param bool success: whether the exchange succeeded
        """
        if not self.credential:
            return
        try:
            self.credential.increment_usage(success=success)
        except Exception:
            _logger.exception(
                "Could not record credential usage for service '%s'; "
                "the exchange itself is unaffected.",
                self.service_code,
            )

    def _serialize_payload_for_log(self, body):
        """Render a request body as a redacted string safe to persist.

        Structured bodies (``json=``) are redacted key by key. Bodies handed to
        ``requests`` as ``data=`` arrive as ``str`` or ``bytes`` instead, and
        those used to bypass redaction entirely: ``_redact_sensitive_data``
        walks dicts and lists and returns every other type untouched, so a
        serialized JSON body was stored verbatim -- secrets and all -- while a
        binary one raised TypeError in ``json.dumps``. Both are parsed back into
        structure here so the same key-level redaction applies.

        A body that will not parse is recorded by size only: one we cannot
        inspect is one we cannot show to be free of secrets, and these rows are
        readable by everyone in ``group_api_gateway_user``. Response bodies keep
        their existing treatment -- they are what the far side sent us, not what
        we sent it, and an unparseable one is usually the error page you need.

        :param body: the request body as passed to ``requests``
        :return: a redacted, length-capped string ready for api.event.log
        :rtype: str
        """
        if not body:
            return ""

        if isinstance(body, (bytes, bytearray)):
            try:
                body = body.decode("utf-8")
            except UnicodeDecodeError:
                return f"<{len(body)} bytes, binary, not logged>"

        if isinstance(body, str):
            length = len(body)
            try:
                body = json.loads(body)
            except ValueError:
                return f"<{length} chars, unparseable, not logged>"
            if not isinstance(body, (dict, list)):
                return f"<{length} chars, unparseable, not logged>"

        if not isinstance(body, (dict, list)):
            # A stream, a file handle, a generator: not inspectable, and
            # reading it here would consume the body.
            return f"<{type(body).__name__}, not logged>"

        return json.dumps(self._redact_sensitive_data(body))[:_MAX_LOGGED_PAYLOAD]

    def _queue_event_log(
        self,
        method,
        url,
        request_kwargs,
        response_data,
        trace_id,
        cache_hit=False,
        error=None,
        error_type=None,
    ):
        """Build the api.event.log values and queue them for the precommit insert.

        Split out of ``_log_request`` so that method is nothing but the
        guarantee that this one cannot take the request down with it.
        """
        # Ensure hooks are registered
        self._ensure_log_hooks()

        safe_headers = self._redact_sensitive_data(request_kwargs.get("headers", {}))
        safe_body = self._serialize_payload_for_log(
            request_kwargs.get("json") or request_kwargs.get("data"),
        )

        # Mask the URL itself before storing (userinfo, query-param tokens).
        safe_url = _mask_sensitive_url(url)

        # Use api.event.log field names (from api_communication).
        # Pass ``company_id`` explicitly so multi-tenant outbound calls
        # land under the effective request tenant (the credential's
        # company), not the endpoint owner.  api.event.log.company_id
        # is computed-with-fallback: a non-zero value here is honoured
        # and the compute only fills in from the channel when missing.
        vals = {
            "direction": "outbound",
            "channel_id": f"api.endpoint.outbound,{self.service.id}",
            "company_id": self.company_id,
            "credential_id": self.credential.id,
            "user_id": self.user_id,
            "request_method": method,
            "request_url": safe_url,
            "request_headers": safe_headers,
            "request_payload": safe_body,
            "trace_id": trace_id,
            "cache_hit": cache_hit,
        }

        if response_data:
            # FIX (t20851 H2): redact response headers and body before
            # persisting. api.event.log rows are readable by the
            # group_api_gateway_user group, so anything that leaks here
            # leaks to every monitoring user.
            safe_response_headers = self._redact_sensitive_data(
                response_data.get("headers") or {},
            )
            safe_response_body = self._redact_sensitive_data(
                response_data.get("body"),
            )
            vals.update(
                {
                    "status_code": response_data.get("status_code"),
                    "response_headers": safe_response_headers,
                    "response_payload": json.dumps(safe_response_body)[
                        :_MAX_LOGGED_PAYLOAD
                    ],
                    "duration_ms": response_data.get("elapsed_ms", 0),
                    "date_completed": fields.Datetime.now(),
                    "state": "success",
                },
            )

        if error:
            vals.update(
                {
                    "error_message": error,
                    "error_type": error_type,
                    "state": "failed",
                },
            )

        # Queue log for batch insert in precommit
        self.env.cr.precommit.data["api.event.log.values"].append(vals)

    def _redact_sensitive_data(self, data, _depth=0, _max_depth=50):
        """Recursively redact sensitive fields from data before logging.

        Case-insensitive, pattern-based (apiKey / API_KEY / oauth_token / …),
        with a depth limit that truncates over-deep structures (circular refs
        or malicious payloads).

        :param data: dict, list, or primitive value to redact
        :param _depth: current recursion depth (internal)
        :param _max_depth: max recursion depth guarding against stack overflow (default 50)
        :return: a redacted copy of the data structure
        :rtype: same as input
        """
        if not data:
            return data

        # SAFETY: Prevent stack overflow on deeply nested structures
        if _depth > _max_depth:
            _logger.warning(
                "Redaction depth limit (%s) exceeded at depth %s. Truncating structure. This may indicate a circular reference or maliciously crafted payload.",
                _max_depth,
                _depth,
            )
            return "***REDACTED_DEEP_NESTING***"

        # Sensitive field patterns are defined at module level so URL masking
        # and payload redaction share the same vocabulary.
        sensitive_patterns = _SENSITIVE_FIELD_PATTERNS

        if isinstance(data, dict):
            redacted = {}
            for key, value in data.items():
                # Check if key contains sensitive pattern (case-insensitive)
                key_lower = str(key).lower()
                if any(pattern in key_lower for pattern in sensitive_patterns):
                    redacted[key] = "***REDACTED***"
                # Recursively redact nested structures with depth tracking
                elif isinstance(value, (dict, list)):
                    redacted[key] = self._redact_sensitive_data(
                        value, _depth + 1, _max_depth
                    )
                else:
                    redacted[key] = value
            return redacted

        if isinstance(data, list):
            # Recursively redact items in lists with depth tracking
            return [
                self._redact_sensitive_data(item, _depth + 1, _max_depth)
                for item in data
            ]

        # Primitive values (str, int, bool, etc.) return as-is
        return data

    def health_check(self):
        """Perform health check on the API"""
        try:
            if self.service.health_check_endpoint:
                response = self.get(
                    self.service.health_check_endpoint,
                    skip_cache=True,
                    skip_logging=True,
                    timeout=5,
                )
                return response["status_code"] == 200
            response = self.request(
                "OPTIONS",
                "/",
                skip_cache=True,
                skip_logging=True,
                timeout=5,
            )
            return True
        except Exception as e:
            # Health check failed - log for debugging but return False
            _logger.debug("Health check failed for %s: %s", self.service_code, e)
            return False


# ==================== Factory Function ====================


def get_api_client(env, service_code, company_id=None, credential_id=None):
    """Return the generic HTTP transport client for a service.

    Transport-framework factory: returns an ``APIGatewayClient`` for every
    service. Downstream modules that add non-HTTP transports override it —
    ``api_gateway`` dispatches ``is_odoo_database`` services to its
    ``OdooDatabaseClient`` and delegates the rest here.

    :param env: Odoo environment
    :param service_code: service code (e.g. 'stripe')
    :param company_id: company ID (optional)
    :param credential_id: specific credential ID (optional)
    :return: APIGatewayClient instance
    :rtype: APIGatewayClient
    """
    # Load service to check type
    service = (
        env["api.endpoint.outbound"]
        .sudo()
        .search(
            [
                ("code", "=", service_code),
                ("active", "=", True),
            ],
            limit=1,
        )
    )

    if not service:
        raise UserError(_("API service '%s' not found or inactive") % service_code)

    # Specialized clients for non-HTTP transports (e.g. the Odoo-to-Odoo
    # database client) live in downstream modules that know those protocols.
    # api_gateway overrides this factory to dispatch is_odoo_database services
    # to OdooDatabaseClient; here in the transport framework we return the
    # generic HTTP client for every service.
    return APIGatewayClient(env, service_code, company_id, credential_id)
