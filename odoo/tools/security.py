import base64
import datetime
import hashlib
import hmac as hmac_lib
import time
import typing
import zlib
from typing import Any

from odoo.libs.debug_log import DebugLog
from odoo.libs.json import dumps as json_dumps
from odoo.libs.json import loads as json_loads

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.api import Environment
    from odoo.orm._typing import BaseModel

_debug = DebugLog(__name__)

consteq = hmac_lib.compare_digest


def hmac(
    env: Environment,
    scope: str,
    message: typing.Any,
    hash_function: Callable[[], Any] = hashlib.sha256,
) -> str:
    if not scope:
        msg = "Non-empty scope required"
        raise ValueError(msg)

    config_parameter: Any = env(su=True)["ir.config_parameter"]
    secret = config_parameter.get_param("database.secret")
    if not secret:
        _debug.logic("security.hmac_secret_missing", scope=scope)
        raise ValueError(
            "The 'database.secret' configuration parameter is missing or empty; "
            "cannot compute a secure HMAC."
        )
    secret = str(secret)
    message = repr((scope, message))
    return hmac_lib.new(
        secret.encode(),
        message.encode(),
        hash_function,
    ).hexdigest()


def hash_sign(
    env: Environment,
    scope: str,
    message_values: typing.Any,
    expiration: datetime.datetime | datetime.timedelta | None = None,
    expiration_hours: float | None = None,
) -> str:
    if expiration and expiration_hours:
        msg = "hash_sign() takes expiration or expiration_hours, not both"
        raise ValueError(msg)
    if message_values is None:
        msg = "hash_sign() requires a message to sign"
        raise ValueError(msg)

    if expiration_hours:
        expiration = datetime.datetime.now() + datetime.timedelta(
            hours=expiration_hours
        )
    elif isinstance(expiration, datetime.timedelta):
        expiration = datetime.datetime.now() + expiration
    expiration_timestamp = 0 if not expiration else int(expiration.timestamp())
    message_strings = json_dumps(message_values)
    hash_value = hmac(
        env,
        scope,
        f"1:{message_strings}:{expiration_timestamp}",
        hash_function=hashlib.sha256,
    )
    token = (
        b"\x01"
        + expiration_timestamp.to_bytes(8, "little")
        + bytes.fromhex(hash_value)
        + message_strings.encode()
    )
    _debug.lifecycle(
        "security.hash_signed",
        scope=scope,
        expires=expiration_timestamp or None,
        message_bytes=len(message_strings),
    )
    return base64.urlsafe_b64encode(token).decode().rstrip("=")


def resolve_hash_signed(
    env: Environment, scope: str, payload: str
) -> typing.Any | None:
    if not isinstance(payload, str):
        _debug.logic("security.hash_signed_rejected", scope=scope, reason="not_str")
        return None
    try:
        token = base64.urlsafe_b64decode(payload.encode() + b"===")
        if token[:1] != b"\x01":
            _debug.logic("security.hash_signed_rejected", scope=scope, reason="version")
            return None
        expiration_bytes, hash_value, message = (
            token[1:9],
            token[9:41].hex(),
            token[41:].decode(),
        )
    except ValueError, TypeError:
        _debug.logic("security.hash_signed_rejected", scope=scope, reason="malformed")
        return None
    expiration_timestamp = int.from_bytes(expiration_bytes, byteorder="little")
    hash_value_expected = hmac(
        env,
        scope,
        f"1:{message}:{expiration_timestamp}",
        hash_function=hashlib.sha256,
    )

    signed = consteq(hash_value, hash_value_expected)
    live = (
        expiration_timestamp == 0
        or datetime.datetime.now().timestamp() < expiration_timestamp
    )
    _debug.logic(
        "security.hash_signed_resolved",
        scope=scope,
        signed=signed,
        live=live,
        expires=expiration_timestamp or None,
    )
    if signed and live:
        return json_loads(message)
    return None


def limited_field_access_token(
    record: BaseModel,
    field_name: str,
    timestamp: str | None = None,
    *,
    scope: str,
) -> str:
    record.check_singleton()
    if not timestamp:
        unique_str = repr((record._name, record.id, field_name))
        two_weeks = 1209600
        start_of_period = int(time.time()) // two_weeks * two_weeks
        adler32_max = 4294967295
        jitter = two_weeks * zlib.adler32(unique_str.encode()) // adler32_max
        timestamp = hex(start_of_period + 2 * two_weeks + jitter)
    token = hmac(
        record.env(su=True),
        scope,
        (record._name, record.id, field_name, timestamp),
    )
    return f"{token}o{timestamp}"


def is_valid_limited_field_access_token(
    record: BaseModel,
    field_name: str,
    access_token: str,
    *,
    scope: str,
) -> bool:
    if not isinstance(access_token, str) or not access_token.isascii():
        _debug.logic(
            "security.field_token_rejected",
            model=record._name,
            field=field_name,
            reason="not_ascii_str",
        )
        return False
    *_, timestamp = access_token.rsplit("o", 1)
    try:
        expiration = datetime.datetime.fromtimestamp(int(timestamp, 16))
    except ValueError, OverflowError, OSError:
        _debug.logic(
            "security.field_token_rejected",
            model=record._name,
            field=field_name,
            reason="timestamp",
        )
        return False
    signed = consteq(
        access_token,
        limited_field_access_token(record, field_name, timestamp, scope=scope),
    )
    live = datetime.datetime.now() < expiration
    _debug.logic(
        "security.field_token_checked",
        model=record._name,
        record=record.id,
        field=field_name,
        signed=signed,
        live=live,
    )
    return signed and live
