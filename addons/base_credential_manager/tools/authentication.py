import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime, timedelta

from odoo.http import request

_logger = logging.getLogger(__name__)

# A bare integer/decimal string is a Unix epoch (ISO 8601 always has separators).
_EPOCH_RE = re.compile(r"^\d+(\.\d+)?$")


def _looks_like_epoch(value):
    """Return True if the string is a bare numeric Unix-epoch timestamp."""
    return bool(_EPOCH_RE.match(value.strip()))


def _get_future_tolerance(env=None):
    """Get future tolerance from config or default."""
    try:
        if env:
            return int(
                env["ir.config_parameter"]
                .sudo()
                .get_param("base_credential_manager.timestamp_future_tolerance", "60"),
            )
        if request and hasattr(request, "env") and request.env:
            return int(
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("base_credential_manager.timestamp_future_tolerance", "60"),
            )
    except ImportError, RuntimeError, ValueError, TypeError:
        pass
    return 60


def _handle_none_signature(env=None):
    """Handle 'none' signature type with security check.

    When the ``base_credential_manager.allow_none_signature`` system parameter is
    not explicitly set to ``"True"``, the request is rejected by returning
    ``False`` — the controller is responsible for turning that into a clean
    401 response. Raising a ``UserError`` from here would bubble up as a
    500 Internal Server Error, which is the wrong signal to send the caller.

    Returns:
        True only if the kill switch is explicitly enabled; False otherwise.

    """
    if env is None:
        try:
            if request and hasattr(request, "env") and request.env:
                env = request.env
        except ImportError, RuntimeError:
            pass

    if env:
        allow_none = (
            env["ir.config_parameter"]
            .sudo()
            .get_param("base_credential_manager.allow_none_signature", default="False")
        )
        if allow_none != "True":
            _logger.warning(
                "Signature type 'none' is disabled. "
                "Set base_credential_manager.allow_none_signature = True to enable "
                "(NEVER in production).",
            )
            return False

    _logger.warning("SECURITY RISK: Signature verification DISABLED")
    return True


def verify_bearer_token(headers, expected_token):
    """Verify bearer token in Authorization header.

    Args:
        headers: HTTP headers dict
        expected_token: Expected token value

    Returns:
        True if token matches

    """
    if not isinstance(headers, dict):
        _logger.error("Headers must be dict, got %s", type(headers).__name__)
        return False

    auth_header = headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        _logger.warning("Authorization header missing or malformed")
        return False

    token = auth_header[7:].strip()

    if not token:
        _logger.warning("Bearer token is empty")
        return False

    if not expected_token:
        _logger.error("No expected token provided")
        return False

    # Constant-time comparison
    return hmac.compare_digest(token, expected_token)


def _verify_custom(verification_method, headers, body, env=None):
    """Execute custom verification method."""
    if not verification_method:
        return False

    try:
        if env is None:
            try:
                if request and hasattr(request, "env") and request.env:
                    env = request.env
            except ImportError, RuntimeError:
                pass

        if env is None:
            _logger.error("No environment for custom verification")
            return False

        parts = verification_method.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError("Invalid method format")

        model_name, method_name = parts
        model = env[model_name].sudo()
        method = getattr(model, method_name, None)

        if not method or not callable(method):
            raise AttributeError(f"Method {method_name} not found")

        return method(headers, body)

    except Exception:
        _logger.exception("Custom verification failed")
        return False


def verify_hmac_signature(
    headers,
    body,
    secret,
    hash_func,
    signature_header="X-Hub-Signature-256",
    signature_prefix="sha256=",
):
    """Verify HMAC signature with constant-time comparison.

    Args:
        headers: HTTP headers dict
        body: Request body string
        secret: Shared secret
        hash_func: Hash function (hashlib.sha256 or hashlib.sha512)
        signature_header: Header containing signature
        signature_prefix: Prefix to remove from signature

    Returns:
        True if signature matches

    """
    if not isinstance(headers, dict):
        _logger.error("Headers must be dict, got %s", type(headers).__name__)
        return False

    signature = headers.get(signature_header)
    if not signature:
        _logger.warning("Signature header '%s' not found", signature_header)
        return False

    if not secret:
        _logger.error("No secret provided for HMAC verification")
        return False

    # Remove prefix if present
    if signature_prefix and signature.startswith(signature_prefix):
        signature = signature[len(signature_prefix) :]

    # Validate hexadecimal
    try:
        int(signature, 16)
    except ValueError:
        _logger.warning("Signature is not valid hexadecimal")
        return False

    # Compute expected signature. The body may arrive as raw bytes (the inbound
    # controller signs the exact bytes received, not a lossily-decoded string) or
    # as text for callers that only have a string; handle both without mangling.
    body_bytes = body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
    expected = hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hash_func,
    ).hexdigest()

    # Constant-time comparison (timing attack prevention)
    return hmac.compare_digest(signature.lower(), expected.lower())


def verify_signature(signature_type, headers, body, secret=None, **kwargs):
    """Verify request signature based on type.

    Args:
        signature_type: Type of signature (bearer, hmac_sha256, hmac_sha512, custom, none)
        headers: HTTP request headers dict
        body: Raw request body string
        secret: Shared secret for verification
        **kwargs: Additional parameters (signature_header, signature_prefix, verification_method)

    Returns:
        True if signature is valid

    """
    try:
        if signature_type == "hmac_sha256":
            return verify_hmac_signature(
                headers,
                body,
                secret,
                hashlib.sha256,
                signature_header=kwargs.get("signature_header", "X-Hub-Signature-256"),
                signature_prefix=kwargs.get("signature_prefix", "sha256="),
            )
        if signature_type == "hmac_sha512":
            return verify_hmac_signature(
                headers,
                body,
                secret,
                hashlib.sha512,
                signature_header=kwargs.get("signature_header", "X-Hub-Signature-512"),
                signature_prefix=kwargs.get("signature_prefix", "sha512="),
            )
        if signature_type in ("bearer", "api_key"):
            return verify_bearer_token(headers, secret)
        if signature_type == "custom":
            verification_method = kwargs.get("verification_method")
            if not verification_method:
                _logger.error("Custom verification requires 'verification_method'")
                return False
            return _verify_custom(verification_method, headers, body, kwargs.get("env"))
        if signature_type == "none":
            return _handle_none_signature(kwargs.get("env"))
        _logger.warning("Unknown signature type: %s", signature_type)
        return False

    except Exception:
        _logger.exception("Signature verification error")
        return False


def verify_timestamp(
    timestamp_value,
    max_age_seconds=300,
    timestamp_format=None,
    future_tolerance_seconds=None,
    env=None,
):
    """Verify timestamp is within acceptable window (replay attack prevention).

    Args:
        timestamp_value: Timestamp (Unix int/float or ISO string)
        max_age_seconds: Maximum age in seconds (default: 300)
        timestamp_format: Format string if parsing custom format
        future_tolerance_seconds: Clock skew tolerance
        env: Odoo environment (optional, for reading config)

    Returns:
        True if timestamp is valid

    """
    try:
        # Convert to datetime (UTC)
        if isinstance(timestamp_value, (int, float)):
            if timestamp_value < 0 or timestamp_value > 253402300799:
                _logger.warning("Timestamp out of bounds: %s", timestamp_value)
                return False
            timestamp_dt = datetime.fromtimestamp(timestamp_value, tz=UTC)
        elif isinstance(timestamp_value, str):
            if timestamp_format:
                timestamp_dt = datetime.strptime(timestamp_value, timestamp_format)
                if timestamp_dt.tzinfo is None:
                    timestamp_dt = timestamp_dt.replace(tzinfo=UTC)
            elif _looks_like_epoch(timestamp_value):
                # Numeric string = Unix epoch seconds (Stripe/Slack/GitHub style),
                # the most common webhook timestamp format.
                epoch = float(timestamp_value.strip())
                if epoch < 0 or epoch > 253402300799:
                    _logger.warning("Timestamp out of bounds: %s", timestamp_value)
                    return False
                timestamp_dt = datetime.fromtimestamp(epoch, tz=UTC)
            else:
                if timestamp_value.endswith("Z"):
                    timestamp_value = timestamp_value[:-1] + "+00:00"
                timestamp_dt = datetime.fromisoformat(timestamp_value)
        else:
            _logger.warning("Invalid timestamp type: %s", type(timestamp_value))
            return False

        now = datetime.now(tz=UTC)

        # Get future tolerance
        if future_tolerance_seconds is None:
            future_tolerance_seconds = _get_future_tolerance(env)

        # Check future
        if timestamp_dt > now + timedelta(seconds=future_tolerance_seconds):
            _logger.warning("Timestamp in future: %s", timestamp_dt)
            return False

        # Check age
        age = (now - timestamp_dt).total_seconds()
        if age > max_age_seconds:
            _logger.warning("Timestamp too old: %ss > %ss", age, max_age_seconds)
            return False

        return True

    except Exception:
        _logger.exception("Timestamp verification error")
        return False
