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


def _get_param_with_legacy(env, suffix, default):
    """Read a config parameter, honouring the legacy api_communication name.

    :return: the parameter value, or ``default`` when neither key is set
    """
    icp = env["ir.config_parameter"].sudo()
    value = icp.get_param(f"base_credential_manager.{suffix}", default=None)
    if value is None:
        # This module is the canonical copy of what used to live in
        # api_communication.tools.authentication (now a re-export shim of this
        # file). Databases configured before the promotion may still carry the
        # parameter under the old api_communication.* key, so the canonical
        # base_credential_manager.* key wins and the legacy key is only the fallback.
        value = icp.get_param(f"api_communication.{suffix}", default=None)
    return default if value is None else value


def _resolve_env(env=None):
    """Return the given env, or the current request's env, or None."""
    if env is not None:
        return env
    try:
        if request and hasattr(request, "env") and request.env:
            return request.env
    except ImportError, RuntimeError:
        pass
    return None


def _get_future_tolerance(env=None):
    """Get future tolerance from config or default."""
    try:
        env = _resolve_env(env)
        if env:
            return int(
                _get_param_with_legacy(env, "timestamp_future_tolerance", "60"),
            )
    except ImportError, RuntimeError, ValueError, TypeError:
        pass
    return 60


def _handle_none_signature(env=None):
    """Handle the 'none' signature type, gated by a security kill switch.

    :return: True only if the kill switch is explicitly enabled, False otherwise
    """
    env = _resolve_env(env)

    if env:
        allow_none = _get_param_with_legacy(env, "allow_none_signature", "False")
        if allow_none != "True":
            # Reject by returning False so the controller can emit a clean 401;
            # raising UserError here would surface as a 500, the wrong signal.
            _logger.warning(
                "Signature type 'none' is disabled. "
                "Set base_credential_manager.allow_none_signature = True to enable "
                "(NEVER in production).",
            )
            return False

    _logger.warning("SECURITY RISK: Signature verification DISABLED")
    return True


def verify_bearer_token(headers, expected_token):
    """Verify a bearer token in the Authorization header.

    :param dict headers: HTTP headers
    :param expected_token: expected token value
    :return: True if the token matches
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
        env = _resolve_env(env)
        if env is None:
            _logger.error("No environment for custom verification")
            return False

        parts = verification_method.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError("Invalid method format")

        model_name, method_name = parts
        # SECURITY: the method is invoked with sudo(), so gate it on a verify_*
        # / _verify_* name. Without this, a verification_method config value could
        # invoke ANY model method with superuser rights (e.g. res.users.unlink),
        # turning endpoint-config write access into arbitrary ORM execution.
        if not method_name.lstrip("_").startswith("verify_"):
            _logger.error(
                "Custom verification method %r rejected: method name must "
                "start with 'verify_' or '_verify_'.",
                verification_method,
            )
            return False

        model = env[model_name].sudo()
        method = getattr(model, method_name, None)

        if not method or not callable(method):
            raise AttributeError(f"Method {method_name} not found")

        return bool(method(headers, body))

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

    :param dict headers: HTTP headers
    :param body: request body (str or bytes)
    :param secret: shared secret
    :param hash_func: hash function (hashlib.sha256 or hashlib.sha512)
    :param signature_header: header containing the signature
    :param signature_prefix: prefix to remove from the signature
    :return: True if the signature matches
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

    :param signature_type: scheme (bearer/api_key, hmac_sha256, hmac_sha512, custom, none)
    :param dict headers: HTTP request headers
    :param body: raw request body (str or bytes)
    :param secret: shared secret for verification
    :param kwargs: extra params (signature_header, signature_prefix, verification_method, env)
    :return: True if the signature is valid
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

    :param timestamp_value: timestamp (Unix int/float or ISO/epoch string)
    :param max_age_seconds: maximum age in seconds (default 300)
    :param timestamp_format: format string for parsing a custom format
    :param future_tolerance_seconds: clock-skew tolerance
    :param env: Odoo environment (optional, for reading config)
    :return: True if the timestamp is valid
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
