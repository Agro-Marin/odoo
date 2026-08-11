import hashlib
import json
import math
import re
from collections import deque
from typing import Any

from .exceptions import ClientError

# ===========================================================================
# VALIDATION UTILITIES
# ===========================================================================


def validate_payload_size(
    payload_bytes: bytes,
    max_size_bytes: int,
) -> tuple[bool, str | None]:
    """Validate that the payload size is within the limit.

    :param payload_bytes: raw payload bytes
    :param max_size_bytes: maximum allowed size in bytes
    :return: (is_valid, error_message)
    :rtype: tuple
    """
    payload_size = len(payload_bytes)

    if payload_size > max_size_bytes:
        return (
            False,
            f"Payload too large: {payload_size} bytes exceeds maximum of {max_size_bytes} bytes "
            f"({max_size_bytes // 1024}KB)",
        )

    return True, None


def validate_content_type(
    content_type: str | None,
    expected: str = "application/json",
) -> tuple[bool, str | None]:
    """Validate the HTTP Content-Type header.

    :param content_type: Content-Type header value
    :param expected: expected content type (default application/json)
    :return: (is_valid, error_message)
    :rtype: tuple
    """
    if not content_type:
        return False, "Missing Content-Type header"

    # Extract main type (ignore charset, boundary, etc.)
    main_type = content_type.split(";")[0].strip().lower()

    if main_type != expected.lower():
        return (
            False,
            f"Invalid Content-Type: expected '{expected}', got '{content_type}'",
        )

    return True, None


def sanitize_error_message(error: str | Exception, max_length: int = 500) -> str:
    """Sanitize an error message for safe logging and display.

    Truncates long messages and masks common sensitive-data patterns.

    :param error: error to sanitize (string or Exception)
    :param max_length: maximum message length (default 500)
    :return: the sanitized message
    :rtype: str
    """
    message = str(error)

    # Truncate if too long
    if len(message) > max_length:
        message = message[:max_length] + "... (truncated)"

    # Remove common sensitive patterns (case-insensitive replacement)
    sensitive_patterns = ["password", "token", "secret", "api_key"]

    for pattern in sensitive_patterns:
        message = re.sub(re.escape(pattern), "***", message, flags=re.IGNORECASE)

    return message


# ===========================================================================
# PAYLOAD HASHING
# ===========================================================================


def compute_payload_hash(payload: dict | str | Any) -> str:
    """Compute the SHA256 hash of a payload for duplicate detection.

    :param payload: payload data (dict, str, or JSON-serializable)
    :return: the SHA256 hexdigest
    :rtype: str
    """
    if isinstance(payload, dict):
        # Normalize JSON for consistent hashing
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    elif isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            normalized = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        except json.JSONDecodeError, ValueError:
            normalized = payload
    else:
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_json_payload(
    body: str,
    max_depth: int = 100,
) -> tuple[bool, dict | None, str | None]:
    """Validate a JSON payload.

    :param body: raw request body string
    :param max_depth: maximum nesting depth (default 100)
    :return: (is_valid, parsed_dict, error_message)
    :rtype: tuple
    """
    if not body or not body.strip():
        return False, None, "Empty payload"

    try:
        parsed = json.loads(body)

        # Check nesting depth
        if not _check_depth(parsed, max_depth):
            return (
                False,
                None,
                f"Payload exceeds maximum nesting depth of {max_depth}",
            )

        return True, parsed, None

    except json.JSONDecodeError as e:
        return False, None, f"Invalid JSON: {e}"
    except Exception as e:
        return False, None, f"Payload validation error: {e}"


def _check_depth(obj: Any, max_depth: int, current_depth: int = 0) -> bool:
    """Return whether the object's nesting depth is within the limit.

    :param obj: object to check
    :param max_depth: maximum allowed depth
    :param current_depth: current depth (used in recursion)
    :return: True if within the limit
    :rtype: bool
    """
    if current_depth > max_depth:
        return False

    if isinstance(obj, dict):
        return all(_check_depth(v, max_depth, current_depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return all(_check_depth(item, max_depth, current_depth + 1) for item in obj)

    return True


def split_large_payload(
    data: list | dict | Any,
    max_size: int = 1024 * 1024,  # 1MB default
) -> list:
    """Split a large payload into chunks that fit APIs with size limits.

    Uses an iterative binary split (no recursion) to avoid stack overflow.

    :param data: list of items, or a single dict, to split
    :param max_size: maximum payload size in bytes
    :return: payloads that each fit within max_size
    :rtype: list
    :raises ClientError: if a single item exceeds max_size
    """
    if not data:
        return []

    # Handle single dict (not a list)
    if not isinstance(data, list):
        payload = json.dumps(data)
        payload_size = len(payload.encode())
        if payload_size >= max_size:
            raise ClientError(
                f"Single payload exceeds max size: {payload_size} bytes "
                f"(limit: {max_size} bytes)",
            )
        return [data]

    # Iterative binary split using queue
    queue = deque([data])
    results = []

    while queue:
        chunk = queue.popleft()

        if not chunk:
            continue

        # Single item - check size
        if len(chunk) == 1:
            payload = json.dumps(chunk)
            payload_size = len(payload.encode())
            if payload_size >= max_size:
                raise ClientError(
                    f"Single item in list exceeds max size: {payload_size} bytes "
                    f"(limit: {max_size} bytes). Cannot split further.",
                )
            results.append(chunk)
            continue

        # Multiple items - check if entire chunk fits
        payload = json.dumps(chunk)
        if len(payload.encode()) < max_size:
            results.append(chunk)
        else:
            # Split in half and add back to queue
            pivot = math.ceil(len(chunk) / 2)
            queue.append(chunk[:pivot])
            queue.append(chunk[pivot:])

    return results


# ===========================================================================
# PAYLOAD NORMALIZATION & CHECKSUM
# ===========================================================================


def normalize_json_payload(payload: dict | str | bytes) -> str:
    """Normalize a JSON payload to canonical form (sorted keys, no whitespace).

    :param payload: JSON payload to normalize (dict, str, or bytes)
    :return: the normalized JSON string
    :rtype: str
    :raises ValueError: if the payload is not valid JSON
    :raises TypeError: if the payload is not a str, dict, or bytes
    """
    if isinstance(payload, dict):
        data = payload
    elif isinstance(payload, bytes):
        try:
            decoded = payload.decode("utf-8")
            data = json.loads(decoded)
        except UnicodeDecodeError as e:
            raise ValueError(f"Cannot decode bytes payload as UTF-8: {e}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON payload: {e}") from e
    elif isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON payload: {e}") from e
    else:
        raise TypeError(
            f"Payload must be str, dict, or bytes, got {type(payload).__name__}",
        )

    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def verify_payload_checksum(
    payload: dict | str | bytes,
    expected_checksum: str,
    algorithm: str = "sha256",
) -> bool:
    """Verify that a payload's checksum matches the expected value.

    :param payload: payload to verify
    :param expected_checksum: expected hexadecimal checksum
    :param algorithm: hash algorithm (default sha256)
    :return: True if the checksum matches
    :rtype: bool
    """
    if not expected_checksum:
        return False

    # Normalize and hash
    if isinstance(payload, dict):
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    elif isinstance(payload, bytes):
        try:
            decoded = payload.decode("utf-8")
            parsed = json.loads(decoded)
            normalized = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        except UnicodeDecodeError, json.JSONDecodeError:
            # Binary data - hash as-is
            hash_func = getattr(hashlib, algorithm)
            actual = hash_func(payload).hexdigest()
            return actual.lower() == expected_checksum.lower()
    elif isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            normalized = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        except json.JSONDecodeError:
            normalized = payload
    else:
        normalized = str(payload)

    hash_func = getattr(hashlib, algorithm)
    actual = hash_func(normalized.encode("utf-8")).hexdigest()
    return actual.lower() == expected_checksum.lower()
