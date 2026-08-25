import ipaddress
import json
import logging
import re
import socket
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
from odoo.addons.credential.tools.session_cache import (
    get_session_cache,
)

_logger = logging.getLogger(__name__)

_URL_SECRET_PATTERNS: list[tuple[re.Pattern[str], object]] = []


def register_url_secret(pattern, replacement):
    _URL_SECRET_PATTERNS.append(
        (re.compile(pattern) if isinstance(pattern, str) else pattern, replacement),
    )


def _apply_registered_secrets(value: str) -> str:
    for pattern, replacement in _URL_SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


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
    "x_amz_security_token",
    "x_amz_signature",
)

_MAX_LOGGED_PAYLOAD = 10000


def _error_type_for_status(status_code):
    if status_code == 401:
        return "auth"
    if status_code == 429:
        return "rate_limit"
    if 400 <= status_code < 500:
        return "validation"
    return "server"


_PRIVATE_SUFFIXES = (".local", ".lan", ".internal", ".home")


def _resolve_addresses(host):
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        return [
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        ]
    except OSError, ValueError:
        return []


def is_private_host(host):
    if not host:
        return False
    host = host.strip("[]").lower()
    addresses = _resolve_addresses(host)
    if addresses:
        return all(
            address.is_private or address.is_loopback or address.is_link_local
            for address in addresses
        )
    return host == "localhost" or host.endswith(_PRIVATE_SUFFIXES)


_URL_IN_TEXT_PATTERN = re.compile(r"https?://[^\s'\"<>]+")

_SENSITIVE_KV_PATTERN = re.compile(
    r"(?i)("
    + "|".join(re.escape(p) for p in _SENSITIVE_FIELD_PATTERNS)
    + r")(\s*=\s*)([^\s&;'\"<>]+)",
)


def _mask_sensitive_text(text):
    if not text:
        return text
    masked = _apply_registered_secrets(str(text))
    masked = _URL_IN_TEXT_PATTERN.sub(lambda m: _mask_sensitive_url(m.group(0)), masked)
    return _SENSITIVE_KV_PATTERN.sub(r"\1\2***REDACTED***", masked)


def _mask_sensitive_url(url: str) -> str:
    masked = _apply_registered_secrets(url)

    try:
        parsed = urlparse(masked)
    except ValueError:
        return masked

    netloc = parsed.netloc
    if "@" in netloc:
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


def _masked_cause(exc: BaseException) -> BaseException:
    masked = tuple(
        _mask_sensitive_text(arg) if isinstance(arg, str) else arg for arg in exc.args
    )
    if masked != exc.args:
        exc.args = masked
    return exc


class OutboundAPIClient:
    def __init__(self, env, endpoint_code, company_id=None, credential_id=None):
        self.env = env
        self.endpoint_code = endpoint_code
        self.company_id = company_id or env.company.id
        self.user_id = env.user.id
        self._credential_header_names = frozenset()

        self.service = (
            env["api.endpoint.outbound"]
            .sudo()
            .search(
                [
                    ("code", "=", endpoint_code),
                    ("active", "=", True),
                ],
                limit=1,
            )
        )

        if not self.service:
            raise CommError(
                _("API service '%s' not found or inactive") % endpoint_code,
            )

        if credential_id:
            self.credential = env["credential.credential"].sudo().browse(credential_id)
            if not self.credential.exists() or not self.credential.active:
                raise CommError(_("Invalid or inactive credential"))
        else:
            self.credential = env["credential.credential"]._get_for_endpoint(
                self.service, company=self.company_id, user=self.user_id
            )

        if not self.credential and self.service.auth_type != "none":
            raise CommError(
                _(
                    "No active credentials for service '%(service)s' and company ID %(company)s",
                    service=endpoint_code,
                    company=self.company_id,
                ),
            )

        if self.credential.is_expired:
            raise CommError(
                _("Credentials have expired on %s") % self.credential.date_expiration,
            )

        self.session = self._get_or_create_session()

        environment = (
            self.credential.environment if self.credential else self.service.environment
        )
        if environment == "production":
            self.base_url = self.service.endpoint_url
        else:
            self.base_url = self.service.endpoint_url_test or self.service.endpoint_url

        _logger.info(
            "OutboundAPIClient initialized: service=%s, company=%s, environment=%s",
            endpoint_code,
            self.company_id,
            self.credential.environment,
        )

    def _get_or_create_session(self):
        cache = get_session_cache(self.env)
        cache_key = (
            f"{self.endpoint_code}:{self.company_id}:{self.credential.credential_hash}"
        )

        session = cache.get(cache_key)

        if session is None:
            session = self._create_session()
            cache.set(cache_key, session)

        return session

    def _create_session(self):
        session = requests.Session()

        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=50,
            max_retries=(self._get_retry_config() if self.service.retry_enabled else 0),
        )

        session.mount("http://", adapter)
        session.mount("https://", adapter)

        session.headers.update(
            {
                "User-Agent": f"Odoo-API-Transport/1.0 ({self.endpoint_code})",
                "Accept": "application/json",
            },
        )

        _logger.debug("Created new session for %s", self.endpoint_code)

        return session

    def _get_retry_config(self):
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
        method = method.upper()
        trace_id = kwargs.pop("trace_id", str(uuid.uuid4()))
        skip_cache = kwargs.pop("skip_cache", False)
        skip_rate_limit = kwargs.pop("skip_rate_limit", False)
        skip_logging = kwargs.pop("skip_logging", False)
        raise_for_status = kwargs.pop("raise_for_status", True)

        url = self._build_url(endpoint)

        if (
            method == "GET"
            and not skip_cache
            and not raw
            and self.service.cache_enabled
        ):
            cached = self._serve_cached(method, url, kwargs, trace_id, skip_logging)
            if cached is not None:
                return cached

        if not skip_rate_limit:
            self.check_rate_limit()

        self._prepare_request(url, kwargs)
        start_time = datetime.now()

        try:
            _logger.info("API Request: %s %s", method, _mask_sensitive_url(url))
            response = self.session.request(
                method=method,
                url=url,
                **kwargs,
            )

            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000

            if raise_for_status:
                response.raise_for_status()

            return self._deliver(
                response, elapsed_ms, raw, method, url, kwargs, trace_id, skip_logging
            )

        except requests.exceptions.Timeout as e:
            error = _mask_sensitive_text(str(e))
            _logger.error("API Timeout: %s - %s", _mask_sensitive_url(url), error)
            self._record_failure(
                method, url, kwargs, trace_id, skip_logging, error, "timeout"
            )
            raise CommTimeoutError(
                _("Request timed out: %s") % _mask_sensitive_url(url)
            ) from _masked_cause(e)

        except requests.exceptions.HTTPError as e:
            error = _mask_sensitive_text(self._extract_error(e.response))
            _logger.error("API HTTP Error: %s - %s", _mask_sensitive_url(url), error)
            status_code = e.response.status_code
            self._record_failure(
                method,
                url,
                kwargs,
                trace_id,
                skip_logging,
                error,
                _error_type_for_status(status_code),
                payload={
                    "status_code": status_code,
                    "headers": dict(e.response.headers or {}),
                    "body": None,
                },
            )
            raise self._http_error_for(status_code, error) from _masked_cause(e)

        except requests.exceptions.RequestException as e:
            error = _mask_sensitive_text(str(e))
            _logger.error("API Request Error: %s - %s", _mask_sensitive_url(url), error)
            self._record_failure(
                method, url, kwargs, trace_id, skip_logging, error, "network"
            )
            raise CommError(_("Request failed: %s") % error) from _masked_cause(e)

        except Exception as e:
            error = _mask_sensitive_text(str(e))
            _logger.exception("Unexpected API error")
            self._record_failure(
                method, url, kwargs, trace_id, skip_logging, error, "other"
            )
            raise CommError(_("Unexpected error: %s") % error) from _masked_cause(e)

    def _prepare_request(self, url, kwargs):
        kwargs["headers"] = self._build_headers(kwargs.pop("headers", {}))

        if "timeout" not in kwargs:
            kwargs["timeout"] = (
                self.service.timeout_connect or 10,
                self.service.timeout_read or 30,
            )
        kwargs.setdefault("verify", self._get_tls_verification(url))
        kwargs.setdefault("auth", self._get_auth())

    def _deliver(
        self, response, elapsed_ms, raw, method, url, kwargs, trace_id, skip_logging
    ):
        failed = response.status_code >= 400
        status_error = self._extract_error(response) if failed else None
        status_error_type = (
            _error_type_for_status(response.status_code) if failed else None
        )

        if raw:
            self._track_usage(not failed)
            if not skip_logging:
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

        if (
            method == "GET"
            and response.status_code == 200
            and self.service.cache_enabled
        ):
            self._store_cached(url, kwargs, response_data)

        self._track_usage(not failed)

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

    def _serve_cached(self, method, url, kwargs, trace_id, skip_logging):
        try:
            cached = (
                self.env["api.response.cache"]
                .sudo()
                .get_cached_response(
                    endpoint_code=self.endpoint_code,
                    url=url,
                    params=kwargs.get("params"),
                    company_id=self.company_id,
                    # Scoped by credential, like the session pool above: the
                    # credential resolves per user, so without it one user's
                    # cached body was served to another in the same company.
                    credential_id=self.credential.id,
                )
            )
        except Exception as cache_error:
            _logger.warning(
                "Failed to retrieve from cache, proceeding with API call: %s",
                cache_error,
                exc_info=True,
            )
            self._increment_cache_error()
            return None

        if not cached:
            return None

        if not skip_logging:
            self._log_request(method, url, kwargs, cached, trace_id, cache_hit=True)
        return cached

    def _store_cached(self, url, kwargs, response_data):
        try:
            self.env["api.response.cache"].sudo().set_cached_response(
                endpoint_code=self.endpoint_code,
                url=url,
                response=response_data,
                params=kwargs.get("params"),
                company_id=self.company_id,
                credential_id=self.credential.id,
            )
        except Exception as cache_error:
            _logger.warning(
                "Failed to save response to cache: %s",
                cache_error,
                exc_info=True,
            )
            self._increment_cache_error()

    def _record_failure(
        self,
        method,
        url,
        kwargs,
        trace_id,
        skip_logging,
        error,
        error_type,
        payload=None,
    ):
        self._track_usage(False)
        if not skip_logging:
            self._log_request(
                method,
                url,
                kwargs,
                payload,
                trace_id,
                error=error,
                error_type=error_type,
            )

    @staticmethod
    def _http_error_for(status_code, error):
        if status_code == 401:
            return AuthenticationError(
                _("Authentication failed: %s") % error, status_code
            )
        if status_code == 429:
            return RateLimitError(_("Rate limit exceeded: %s") % error, status_code)
        if 400 <= status_code < 500:
            return ClientError(_("Client error: %s") % error, status_code)
        return ServerError(_("Server error: %s") % error, status_code)

    def get(self, endpoint, **kwargs):
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint, **kwargs):
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint, **kwargs):
        return self.request("PUT", endpoint, **kwargs)

    def patch(self, endpoint, **kwargs):
        return self.request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint, **kwargs):
        return self.request("DELETE", endpoint, **kwargs)

    def post_bulk(self, endpoint, items, max_payload_size=None, **kwargs):
        if not isinstance(items, list):
            raise ClientError("post_bulk requires a list of items")

        max_size = max_payload_size or (1024 * 1024)

        chunks = split_large_payload(items, max_size=max_size)

        if len(chunks) > 1:
            _logger.info(
                "Payload split into %d chunks for %s (max size: %d bytes)",
                len(chunks),
                endpoint,
                max_size,
            )

        responses = []
        for i, chunk in enumerate(chunks, 1):
            _logger.debug(
                "Sending chunk %d/%d with %d items to %s",
                i,
                len(chunks),
                len(chunk) if isinstance(chunk, list) else 1,
                endpoint,
            )

            chunk_kwargs = kwargs.copy()
            chunk_kwargs["json"] = chunk

            response = self.post(endpoint, **chunk_kwargs)
            responses.append(response)

        return responses

    def _build_url(self, endpoint):
        if endpoint.startswith(("http://", "https://")):
            return endpoint

        try:
            parsed = urlparse(self.base_url)

            if parsed.scheme not in ("http", "https"):
                raise ValueError(
                    f"Invalid URL scheme '{parsed.scheme}' for service '{self.endpoint_code}'. "
                    f"Expected 'http' or 'https'.",
                )

            if not parsed.netloc:
                raise ValueError(
                    f"Missing hostname in base URL for service '{self.endpoint_code}': {self.base_url}"
                )

            if parsed.port is not None:
                if not (0 < parsed.port <= 65535):
                    raise ValueError(
                        f"Invalid port {parsed.port} in base URL for service '{self.endpoint_code}'. "
                        f"Port must be between 1 and 65535.",
                    )

            hostname = parsed.hostname or parsed.netloc.split(":")[0]
            if hostname not in ("localhost", "127.0.0.1"):
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", hostname):
                    try:
                        ipaddress.ip_address(hostname)
                    except ValueError as e:
                        raise ValueError(
                            f"Invalid IP address '{hostname}' in base URL for service '{self.endpoint_code}': {e}",
                        ) from e

        except ValueError as e:
            raise ValueError(
                f"Invalid base URL format for service '{self.endpoint_code}': {self.base_url}\n"
                f"Error: {e}\n"
                f"Expected format: https://api.example.com or https://api.example.com/v1",
            ) from e

        base = self.base_url.rstrip("/")
        endpoint_normalized = endpoint.lstrip("/")

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
        credential_headers = (
            self.credential.get_auth_headers() if self.credential else {}
        )
        self._credential_header_names = frozenset(
            str(name).lower() for name in credential_headers
        )
        headers = dict(credential_headers)

        if self.service.api_version:
            if self.service.api_version_header:
                headers.setdefault(
                    self.service.api_version_header, self.service.api_version
                )
            if self.service.send_version_headers:
                headers.setdefault("API-Version", self.service.api_version)
                headers.setdefault("X-API-Version", self.service.api_version)

        if additional_headers:
            headers.update(additional_headers)

        return headers

    _HTTP_AUTH_TYPES = ("basic", "digest")

    def _get_auth(self):
        if self.service.auth_type not in self._HTTP_AUTH_TYPES:
            return None
        if not self.credential:
            return None
        pair = self.credential.get_basic_auth()
        if self.service.auth_type == "digest":
            return HTTPDigestAuth(*pair) if pair else None
        return pair

    def _get_tls_verification(self, url):
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
                % {"host": host, "service": self.endpoint_code},
            )
        return False

    def _parse_response(self, response, elapsed_ms):
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            _logger.debug("Response is not JSON: %s. Using text content.", e)
            body = response.text

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
            _logger.debug("Could not extract error from JSON: %s", e)
            return response.text[:500]

    def _increment_cache_error(self):
        try:
            self.service.sudo().write(
                {
                    "cache_error_count": self.service.cache_error_count + 1,
                    "cache_last_error": fields.Datetime.now(),
                },
            )
        except Exception as e:
            _logger.debug("Failed to increment cache error counter: %s", e)

    def _ensure_log_hooks(self):
        if "api.event.log.values" not in self.env.cr.precommit.data:
            self.env.cr.precommit.data["api.event.log.values"] = []

            @self.env.cr.precommit.add
            def batch_create_logs():
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
        failed = bool(error) or (status_code is not None and status_code >= 400)
        if failed and not error:
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
            error=error,
            error_type=(
                _error_type_for_status(status_code)
                if status_code and status_code >= 400
                else ("network" if error else None)
            ),
        )

    def check_rate_limit(self):
        if not self.service.check_rate_limit(company_id=self.company_id):
            raise RateLimitError(
                _("Rate limit exceeded for service '%s'. Please try again later.")
                % self.endpoint_code,
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
        if not self.credential:
            return
        try:
            self.credential.increment_usage(success=success)
        except Exception:
            _logger.exception(
                "Could not record credential usage for service '%s'; "
                "the exchange itself is unaffected.",
                self.endpoint_code,
            )

    def _serialize_payload_for_log(self, body):
        if not body:
            return ""

        if not self.service.log_request_payload:
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
            return f"<{type(body).__name__}, not logged>"

        return json.dumps(self._redact_sensitive_data(body))[:_MAX_LOGGED_PAYLOAD]

    EVENT_LOG_ANNOTATIONS_KEY = "api_event_log_annotations"
    _ANNOTATION_FIELDS = ("tags", "origin_model", "origin_record_id")

    def _event_log_annotations(self):
        raw = self.env.context.get(self.EVENT_LOG_ANNOTATIONS_KEY) or {}
        if not isinstance(raw, dict):
            return {}
        return {
            key: value
            for key, value in raw.items()
            if key in self._ANNOTATION_FIELDS and value
        }

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
        self._ensure_log_hooks()

        safe_headers = self._redact_headers(request_kwargs.get("headers"))
        safe_body = self._serialize_payload_for_log(
            request_kwargs.get("json") or request_kwargs.get("data"),
        )

        safe_url = _mask_sensitive_url(url)

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
            safe_response_headers = self._redact_sensitive_data(
                response_data.get("headers") or {},
            )
            safe_response_body = self._redact_sensitive_data(
                response_data.get("body"),
            )
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
                vals["error_type"] = _error_type_for_status(status_code)

        if error:
            vals.update(
                {
                    "error_message": _mask_sensitive_text(error),
                    "error_type": error_type,
                    "state": "failed",
                },
            )

        vals.update(self._event_log_annotations())

        self.env.cr.precommit.data["api.event.log.values"].append(vals)

    def _redact_headers(self, headers):
        if not isinstance(headers, dict):
            return {}
        by_provenance = {
            key: (
                "***REDACTED***"
                if str(key).lower() in self._credential_header_names
                else value
            )
            for key, value in headers.items()
        }
        return self._redact_sensitive_data(by_provenance)

    def _redact_sensitive_data(self, data, _depth=0, _max_depth=50):
        if not data:
            return data

        if _depth > _max_depth:
            _logger.warning(
                "Redaction depth limit (%s) exceeded at depth %s. Truncating structure. This may indicate a circular reference or maliciously crafted payload.",
                _max_depth,
                _depth,
            )
            return "***REDACTED_DEEP_NESTING***"

        sensitive_patterns = _SENSITIVE_FIELD_PATTERNS

        if isinstance(data, dict):
            redacted = {}
            for key, value in data.items():
                key_lower = str(key).lower().replace("-", "_")
                if any(pattern in key_lower for pattern in sensitive_patterns):
                    redacted[key] = "***REDACTED***"
                elif isinstance(value, (dict, list)):
                    redacted[key] = self._redact_sensitive_data(
                        value, _depth + 1, _max_depth
                    )
                else:
                    redacted[key] = value
            return redacted

        if isinstance(data, list):
            return [
                self._redact_sensitive_data(item, _depth + 1, _max_depth)
                for item in data
            ]

        return data

    def health_check(self):
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
            _logger.debug("Health check failed for %s: %s", self.endpoint_code, e)
            return False


def get_api_client(env, endpoint_code, company_id=None, credential_id=None):
    service = (
        env["api.endpoint.outbound"]
        .sudo()
        .search(
            [
                ("code", "=", endpoint_code),
                ("active", "=", True),
            ],
            limit=1,
        )
    )

    if not service:
        raise UserError(_("API service '%s' not found or inactive") % endpoint_code)

    return OutboundAPIClient(env, endpoint_code, company_id, credential_id)
