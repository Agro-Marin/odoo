import base64
import binascii
import enum
import hashlib
import hmac
import json
import time
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils


class InvalidVapidError(Exception):
    pass


class Algorithm(enum.Enum):
    ES256 = "ES256"
    HS256 = "HS256"


def _generate_keys(
    key_encoding: serialization.Encoding,
    key_format: serialization.PublicFormat,
) -> tuple[bytes, bytes]:
    private_object = ec.generate_private_key(ec.SECP256R1())
    private_int = private_object.private_numbers().private_value
    private_bytes = private_int.to_bytes(32, "big")
    public_object = private_object.public_key()
    public_bytes = public_object.public_bytes(
        encoding=key_encoding,
        format=key_format,
    )
    return private_bytes, public_bytes


def generate_vapid_keys() -> tuple[str, str]:
    private, public = _generate_keys(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private_string = base64.urlsafe_b64encode(private).decode("ascii").strip("=")
    public_string = base64.urlsafe_b64encode(public).decode("ascii").strip("=")
    return private_string, public_string


def base64_decode_with_padding(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "==")


def _generate_jwt(claims: dict[str, Any], key: str, algorithm: Algorithm) -> str:
    JOSE_header = base64.urlsafe_b64encode(
        json.dumps({"typ": "JWT", "alg": algorithm.value}).encode()
    )
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode())
    unsigned_token = "{}.{}".format(
        JOSE_header.decode().strip("="), payload.decode().strip("=")
    )
    key_decoded = base64_decode_with_padding(key)

    match algorithm:
        case Algorithm.HS256:
            signature = hmac.new(
                key_decoded, unsigned_token.encode(), hashlib.sha256
            ).digest()
            sig = base64.urlsafe_b64encode(signature)
        case Algorithm.ES256:
            private_key = ec.derive_private_key(
                int(binascii.hexlify(key_decoded), 16), ec.SECP256R1()
            )
            signature = private_key.sign(
                unsigned_token.encode(), ec.ECDSA(hashes.SHA256())
            )
            (r, s) = utils.decode_dss_signature(signature)
            sig = base64.urlsafe_b64encode(
                r.to_bytes(32, "big") + s.to_bytes(32, "big")
            )
        case _:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

    return "{}.{}".format(unsigned_token, sig.decode().strip("="))


def sign(claims: dict[str, Any], key: str, ttl: int, algorithm: Algorithm) -> str:
    non_padded_key = key.strip("=")
    if not ttl:
        raise ValueError("A JWT requires a non-zero ttl for its 'exp' claim.")
    claims = {**claims, "exp": int(time.time()) + ttl}
    return _generate_jwt(claims, non_padded_key, algorithm=algorithm)
