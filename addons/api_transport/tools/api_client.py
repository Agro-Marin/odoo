import ipaddress
import json
import logging
import re
import uuid
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPDigestAuth
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


def _error_type_for_status(status_code):
    """Map an HTTP status onto the ``api.event.log.error_type`` selection.

    The historical ``"http"`` value was not in the selection and broke the
    precommit batch insert (ValueError, rolling back the whole transaction),
    so every status has to land on one of the declared values.

    :param int status_code: the HTTP response status
    :return: one of auth / rate_limit / validation / server
    :rtype: str
    """
    if status_code == 401:
        return "auth"
    if status_code == 429:
        return "rate_limit"
    if 400 <= status_code < 500:
        return "validation"
    return "server"


def is_private_host(host):
    """Whether a host is on a private network.

    Used to bound where TLS verification may be turned off: a self-signed
    certificate is unverifiable by construction on a LAN device, but on a
    public name it is a defence being removed rather than a defect being
    accommodated -- and what leaks is the credential, to whoever answered.

    An IP literal is classified from the address itself. A DNS name is treated
    as public unless it carries a private-use suffix; deliberately no lookup,
    because resolving at validation time makes the answer depend on the
    resolver, and an attacker who controls DNS could make a public name test
    private exactly when it mattered.

    :param str host: hostname or IP literal, no scheme or port
    :return: True when disabling verification is defensible
    :rtype: bool
    """
    if not host:
        return False
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith((".local", ".lan", ".internal", ".home")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        address.is_private or address.is_loopback or address.is_link_local,
    )


def _mask_telegram_token(match):
    """Mask a Telegram bot token, keeping a short tail for debugging."""
    bot_id = match.group(1)
    secret = match.group(2)
    suffix = match.group(3)
    if len(secret) > 4:
        return f"/bot{bot_id}:***...{secret[-4:]}{suffix}"
    return f"/bot{bot_id}:****{suffix}"


# A URL sitting inside a longer string. Deliberately stops at whitespace and at
# the quoting characters an exception message wraps a URL in, so the trailing
# ")" of "(Caused by ...)" is not swallowed into the host.
_URL_IN_TEXT_PATTERN = re.compile(r"https?://[^\s'\"<>]+")

# ``key=value`` where the key looks sensitive. Catches a bare query string
# quoted in an error message, which never reaches urlparse as a URL.
_SENSITIVE_KV_PATTERN = re.compile(
    r"(?i)("
    + "|".join(re.escape(p) for p in _SENSITIVE_FIELD_PATTERNS)
    + r")(\s*=\s*)([^\s&;'\"<>]+)",
)


def _mask_sensitive_text(text):
    """Mask credentials embedded in free text, for error messages.

    ``_mask_sensitive_url`` only helps when the whole string is a URL. An
    exception message is a sentence with a URL somewhere inside it, and
    ``requests`` builds those from the full request URL -- verified: the
    ``str()`` of a ConnectionError to ``/file/bot<token>/x`` contains the token
    verbatim. That string is what lands in ``api.event.log.error_message``,
    which every monitoring user can read, so it has to be masked like the
    ``request_url`` beside it already is.

    Telegram is the concrete case (the token is a path segment, not a query
    param), but any credential-in-URL scheme is covered by the same three
    passes. Request and response *headers* are redacted separately.

    :param text: arbitrary text, typically ``str(exception)``
    :return: the text with credentials masked
    :rtype: str
    """
    if not text:
        return text
    masked = _TELEGRAM_TOKEN_PATTERN.sub(_mask_telegram_token, str(text))
    masked = _URL_IN_TEXT_PATTERN.sub(lambda m: _mask_sensitive_url(m.group(0)), masked)
    return _SENSITIVE_KV_PATTERN.sub(r"\1\2***REDACTED***", masked)


def _mask_sensitive_url(url: str) -> str:
    """Mask sensitive data in a URL for safe logging.

    Masks Telegram bot tokens (keeping a short tail), URL userinfo, and
    sensitive query params (token, secret, api_key, authorization, …).

    :param url: the URL to mask
    :return: the URL with sensitive parts masked, or the original if unparseable
    :rtype: str
    """
    # Step 1: Telegram-specific token masking (keeps tail for debugging)
    masked = _TELEGRAM_TOKEN_PATTERN.sub(_mask_telegram_token, url)

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
        environment = (
            self.credential.environment if self.credential else self.service.environment
        )
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
        :param raise_for_status: When False, a 4xx/5xx is returned to the caller
            like any other response instead of being raised as a ClientError or
            ServerError. For APIs that answer with a *useful* body under an
            error status: SW, the Mexican PAC, reports a CFDI already stamped as
            HTTP 400 whose ``messageDetail`` carries the signed XML, so raising
            throws away the very thing the caller came for. ``_extract_error``
            keeps only ``message``, which is not enough. The exchange is still
            logged as failed and still counted against the credential — only the
            control flow changes. Check ``["status_code"]`` on the way out.
        """
        method = method.upper()
        trace_id = kwargs.pop("trace_id", str(uuid.uuid4()))
        skip_cache = kwargs.pop("skip_cache", False)
        skip_rate_limit = kwargs.pop("skip_rate_limit", False)
        skip_logging = kwargs.pop("skip_logging", False)
        raise_for_status = kwargs.pop("raise_for_status", True)

        url = self._build_url(endpoint)

        # Check cache - failures shouldn't break the API call.
        #
        # `not raw` is load-bearing, not an optimisation. The cache stores
        # parsed bodies, so serving one to a raw caller returns a dict where the
        # documented return type is a live Response, and the caller's
        # `.content` / `.iter_lines()` raises AttributeError. The asymmetry made
        # it worse: the raw branch returns before the write below, so a raw call
        # never populates the cache but could be served an entry a non-raw call
        # to the same URL had left there -- a bug that only appears once two
        # callers share a service, and then looks like a caller's fault.
        if method == "GET" and not skip_cache and not raw and self.service.cache_enabled:
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

        # Resolved BEFORE the try, deliberately. This is a configuration check,
        # not an exchange: inside, the broad `except Exception` below would turn
        # its refusal into a CommError, and a caller mapping CommError to
        # "cannot connect" would report a security misconfiguration as a network
        # fault. Nothing has been sent at this point, and nothing will be.
        #
        # setdefault, not an override: a caller passing verify explicitly has
        # said something more specific than the record's default.
        kwargs.setdefault("verify", self._get_tls_verification(url))

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

            if raise_for_status:
                response.raise_for_status()

            # Only reachable with raise_for_status=False: the caller wants the
            # body of a 4xx/5xx. The exchange is still a failure for the audit
            # trail and the credential's success rate; it just does not raise.
            failed = response.status_code >= 400
            status_error = self._extract_error(response) if failed else None
            status_error_type = (
                _error_type_for_status(response.status_code) if failed else None
            )

            # Streaming / raw passthrough: hand the live Response back to the
            # caller without consuming or parsing the body. Used by the AI
            # clients' streaming_* methods, which iterate the response
            # themselves. The body must not be touched here.
            if raw:
                self._track_usage(not failed)
                if not skip_logging:
                    # Metadata only: status, headers and timing, never the body.
                    # Reading the body here would consume the stream the caller
                    # asked to be handed intact. Passing None instead left the
                    # row at its "pending" default with no status and no
                    # duration -- a completed exchange recorded as one that
                    # never came back.
                    self._log_request(
                        method,
                        url,
                        kwargs,
                        {
                            "status_code": response.status_code,
                            "headers": dict(response.headers),
                            "body": None,
                            "elapsed_ms": elapsed_ms,
                        },
                        trace_id,
                        error=status_error,
                        error_type=status_error_type,
                    )
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
            self._track_usage(not failed)

            # Log request
            if not skip_logging:
                self._log_request(
                    method,
                    url,
                    kwargs,
                    response_data,
                    trace_id,
                    error=status_error,
                    error_type=status_error_type,
                )

            return response_data

        except requests.exceptions.Timeout as e:
            # Masked at the source, so every downstream use -- this log line, the
            # api.event.log row, and the exception raised below -- is safe by
            # construction rather than by each site remembering to.
            error = _mask_sensitive_text(str(e))
            _logger.error("API Timeout: %s - %s", _mask_sensitive_url(url), error)
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

            raise CommTimeoutError(
                _("Request timed out: %s") % _mask_sensitive_url(url)
            ) from e

        except requests.exceptions.HTTPError as e:
            error = _mask_sensitive_text(self._extract_error(e.response))
            _logger.error("API HTTP Error: %s - %s", _mask_sensitive_url(url), error)
            self._track_usage(False)

            status_code = e.response.status_code
            event_error_type = _error_type_for_status(status_code)

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
            error = _mask_sensitive_text(str(e))
            _logger.error("API Request Error: %s - %s", _mask_sensitive_url(url), error)
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
            error = _mask_sensitive_text(str(e))
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
        """Build the ``auth`` object requests should use, if any.

        Digest cannot be expressed as a header the way bearer and api_key are:
        the server answers the first request with a 401 carrying a nonce, and
        the client has to hash the credential against it and repeat the
        request. ``HTTPDigestAuth`` is what performs that exchange, so this is
        the only auth type that has to arrive as an ``auth`` object.

        Everything else keeps its existing behaviour, including the quirk that
        a credential carrying username and password contributes a basic-auth
        pair whatever the service's ``auth_type`` says. That predates this
        method being auth-type aware at all; narrowing it now would silently
        stop sending basic auth for any service that has been relying on the
        accident, which is not a change to make from here.

        :return: an auth object, a ``(user, password)`` pair, or None
        """
        if not self.credential:
            return None
        pair = self.credential.get_basic_auth()
        if self.service.auth_type == "digest":
            return HTTPDigestAuth(*pair) if pair else None
        return pair

    def _get_tls_verification(self, url):
        """Whether to verify the TLS certificate for this URL.

        Enforced per request rather than only by the constraint on the service
        record, because a record whose callers pass absolute URLs -- a device
        per row, a host per tenant -- has a placeholder ``endpoint_url`` that
        the constraint can only ever check instead of the real target. This is
        the point where the actual host is known.

        :param str url: the absolute URL about to be called
        Raised as a UserError, not a CommError, and that matters: callers wrap
        this transport in their own error ladders, and a module catching
        CommError to say "cannot connect to the device" would report a security
        misconfiguration as a network fault -- sending an operator to debug
        cabling instead of fixing the record. It is not a communication
        failure; nothing was sent, and deliberately so.

        :return: the value to pass to requests as ``verify``
        :rtype: bool
        :raises UserError: if verification is off for a public host
        """
        if self.service.verify_tls:
            return True
        host = urlparse(url).hostname or ""
        if not is_private_host(host):
            raise UserError(
                _(
                    "Refusing to call '%(host)s' with TLS verification disabled: "
                    "it is not a private-network host, so the credential for "
                    "service '%(service)s' would be exposed to whoever answers.",
                )
                % {"host": host, "service": self.service_code},
            )
        return False

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

    def log_external_exchange(
        self,
        method,
        url,
        *,
        request_body=None,
        status_code=None,
        elapsed_ms=0,
        error=None,
        trace_id=None,
    ):
        """Record an exchange this client did not itself perform.

        Some protocols cannot be driven through ``request``. zeep builds and
        sends its own SOAP envelopes, and giving it ``self.session`` — which is
        public for exactly this — buys connection pooling and the retry adapter,
        but everything inside ``request`` is bypassed: the rate-limit check, the
        ``api.event.log`` row and the redaction. The Mexican PAC is the concrete
        case; Finkok and Solución Factible are SOAP and only SW is REST.

        This closes the logging half. It deliberately goes through
        ``_log_request`` rather than writing a row directly, so the redaction
        vocabulary and the row schema stay in one place — a second copy would
        drift, and the copy that drifts is the one that leaks.

        Rate limiting is *not* applied here: this is called after the exchange
        has happened, and a limiter consulted after the fact would only ever
        report. Call ``check_rate_limit`` before handing the session over if the
        caller needs it enforced.

        :param str method: the HTTP verb actually used, usually "POST"
        :param str url: the absolute URL called
        :param request_body: the request payload, for redacted storage
        :param int status_code: the HTTP status, when the caller knows it
        :param float elapsed_ms: measured duration
        :param str error: an error description, when the exchange failed
        :param str trace_id: correlation id; generated when omitted
        """
        failed = bool(error) or (status_code is not None and status_code >= 400)
        if failed and not error:
            # `_log_request` derives `state` from the error *text*, not from the
            # status, so a failing status with no message would be recorded as a
            # success. Give it something true to say rather than widen the
            # contract of a method four other paths depend on.
            error = f"HTTP {status_code}"
        self._track_usage(not failed)
        response_data = {
            "status_code": status_code or 0,
            "headers": {},
            "body": None,
            "elapsed_ms": elapsed_ms,
        }
        self._log_request(
            method,
            url,
            {"data": request_body} if request_body is not None else {},
            response_data,
            trace_id or str(uuid.uuid4()),
            # Not masked here on purpose. `_queue_event_log` masks every
            # `error` it stores, so the sink guarantees it for any caller —
            # masking again at this call site would be harmless (the pass is
            # idempotent) but would imply the guarantee lives with the caller,
            # which is how the gap this closes came to exist.
            error=error,
            error_type=(
                _error_type_for_status(status_code)
                if status_code and status_code >= 400
                else ("network" if error else None)
            ),
        )

    def check_rate_limit(self):
        """Consult the limiter for an exchange made outside ``request``.

        Separate from the logging call because it has to happen *before* the
        exchange, and because a caller handing the session to another library
        may make several calls over one client.

        :raises RateLimitError: the service's bucket is empty
        """
        if not self.service.rate_limit_enabled:
            return
        if not self.rate_limiter.check_limit():
            raise RateLimitError(
                _("Rate limit exceeded for service '%s'. Please try again later.")
                % self.service_code,
            )

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
        readable by everyone in ``group_api_gateway_user``. Redaction matches
        key *names*, though, so a service whose payload is secret whatever it
        calls its fields can opt out of storing bodies altogether with
        ``log_request_payload``. Response bodies keep
        their existing treatment -- they are what the far side sent us, not what
        we sent it, and an unparseable one is usually the error page you need.

        :param body: the request body as passed to ``requests``
        :return: a redacted, length-capped string ready for api.event.log
        :rtype: str
        """
        if not body:
            return ""

        if not self.service.log_request_payload:
            # The service has declared its bodies unfit to store. Say so rather
            # than leaving the column empty, which reads as "there was no body".
            return "<suppressed by service configuration>"

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
            # State comes from the status, not from whether anyone wrote an
            # error message. This used to be an unconditional "success", so a
            # 4xx/5xx whose body was empty recorded as a successful exchange:
            # ``_extract_error`` falls back to ``response.text``, an empty body
            # gives "", and the ``if error`` below never fires. A bodiless 502
            # from a proxy is the ordinary shape of that. ``_track_usage``
            # already counted it as failed, so the row disagreed with the
            # credential's own success rate.
            status_code = response_data.get("status_code")
            vals.update(
                {
                    "status_code": status_code,
                    "response_headers": safe_response_headers,
                    "response_payload": json.dumps(safe_response_body)[
                        :_MAX_LOGGED_PAYLOAD
                    ],
                    "duration_ms": response_data.get("elapsed_ms", 0),
                    "date_completed": fields.Datetime.now(),
                    "state": "failed" if (status_code or 0) >= 400 else "success",
                },
            )
            if (status_code or 0) >= 400:
                # Classify from the status for the same reason. The ``if error``
                # block below overwrites this when a message did arrive, so a
                # caller that passes its own error_type still wins; this only
                # fills in the row that would otherwise be failed-with-no-kind.
                vals["error_type"] = _error_type_for_status(status_code)

        if error:
            # Masked again here, not only where ``request`` assigns it. That is
            # deliberate belt-and-braces: masking at the source also covers the
            # raised exception and the server log, which this cannot reach, but
            # it only protects errors that came from ``request``. Anything
            # calling ``_log_request`` from outside that method -- logging an
            # exchange some other library performed, say -- would otherwise hand
            # a raw exception string straight to a stored row. The pass is
            # idempotent: a redacted value contains no key=value pair to match,
            # and a masked Telegram token no longer matches the token pattern.
            vals.update(
                {
                    "error_message": _mask_sensitive_text(error),
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
