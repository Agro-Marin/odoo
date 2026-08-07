"""Pure-stdlib password hashing compatible with passlib's $pbkdf2-sha512$ format.

Replaces passlib (abandoned since 2020, broken on Python 3.13+) with ~100 lines
of stdlib code. All existing password hashes in databases remain valid.
"""

import binascii
import hashlib
import hmac
import os
import re
from base64 import b64decode, b64encode

__all__ = ["CryptContext", "pbkdf2_sha512_hash"]

_DEFAULT_ROUNDS = 600_000
#: Ceiling on the cost parameter read out of a stored hash.  ~16x the default,
#: so a deliberate future increase still verifies, while a hostile or corrupt
#: value cannot turn one login attempt into an unbounded CPU burn.
_MAX_ROUNDS = 10_000_000
_SALT_SIZE = 16
_HASH_SIZE = 64
_MCF_RE = re.compile(r"^\$pbkdf2-sha512\$(\d+)\$([^$]+)\$([^$]+)$")


def _ab64_encode(data: bytes) -> str:
    """Encode bytes using passlib's 'adapted base64' (. instead of +, no padding)."""
    return b64encode(data).rstrip(b"=").replace(b"+", b".").decode("ascii")


def _ab64_decode(data: str) -> bytes:
    """Decode passlib's 'adapted base64' back to bytes.

    ``-len(b) % 4`` (not ``4 - len(b) % 4``): the latter appends four ``=`` when
    the length is already a multiple of four.  b64decode happens to tolerate the
    surplus, so nothing broke, but the two forms only agree by accident and the
    ~4/4-length case never occurs for the 16-byte salt / 64-byte checksum this
    module writes.
    """
    b = data.replace(".", "+").encode("ascii")
    b += b"=" * (-len(b) % 4)
    return b64decode(b)


def _pbkdf2_sha512(password: str, salt: bytes, rounds: int) -> bytes:
    """Raw PBKDF2-SHA512 hash."""
    return hashlib.pbkdf2_hmac(
        "sha512", password.encode("utf-8"), salt, rounds, dklen=_HASH_SIZE
    )


def _format_hash(rounds: int, salt: bytes, checksum: bytes) -> str:
    """Format as passlib-compatible MCF string."""
    return f"$pbkdf2-sha512${rounds}${_ab64_encode(salt)}${_ab64_encode(checksum)}"


def _parse_hash(hash_str: str) -> tuple[int, bytes, bytes] | None:
    """Parse an MCF hash string; return (rounds, salt_bytes, checksum_bytes) or None.

    A hash that *looks* like the MCF format but whose salt/checksum is not valid
    base64 is unparseable, not a crash: ``_MCF_RE`` accepts ``[^$]+`` for both
    fields, so ``$pbkdf2-sha512$1$a$b`` matched here and then blew up inside
    ``b64decode`` with ``binascii.Error``.  That exception escaped
    :meth:`CryptContext.verify`, which every login path calls with a hash read
    straight from ``res_users.password`` — a single truncated or hand-edited row
    (bad restore, partial migration, manual UPDATE) turned "wrong password" into
    an uncaught HTTP 500 on the login route.  Returning ``None`` routes it to the
    same "does not verify" outcome as any other unrecognised hash.
    """
    m = _MCF_RE.match(hash_str)
    if not m:
        return None
    try:
        rounds = int(m.group(1))
        if not 0 < rounds <= _MAX_ROUNDS:
            # The cost parameter comes from the stored hash, so it is only as
            # trustworthy as the row it was read from.  Unbounded, a single
            # doctored or corrupt value ($pbkdf2-sha512$99999999999$...) makes
            # every verify against that account occupy a worker inside
            # pbkdf2_hmac for as long as the attacker cares to specify -- and
            # the same CryptContext backs config.verify_admin_password, whose
            # hash comes from a file.  Treat it as unparseable, which routes it
            # to the same "does not verify" outcome as any other bad hash.
            return None
        return rounds, _ab64_decode(m.group(2)), _ab64_decode(m.group(3))
    except binascii.Error, ValueError:
        return None


def pbkdf2_sha512_hash(password: str, rounds: int = _DEFAULT_ROUNDS) -> str:
    """Hash a password using PBKDF2-SHA512. Return an MCF-formatted string."""
    salt = os.urandom(_SALT_SIZE)
    checksum = _pbkdf2_sha512(password, salt, rounds)
    return _format_hash(rounds, salt, checksum)


class CryptContext:
    """Minimal CryptContext supporting pbkdf2_sha512 + plaintext schemes.

    API-compatible with the subset of passlib.context.CryptContext used by Odoo.
    """

    def __init__(
        self,
        schemes: list[str] | None = None,
        *,
        deprecated: list[str] | None = None,
        _autoload: bool = True,
        **kwargs: object,
    ) -> None:
        """Build a context over the given schemes.

        :param schemes: accepted schemes, most preferred first; the head is the
            primary scheme used by :meth:`hash`. Defaults to ``pbkdf2_sha512``.
        :param deprecated: schemes whose hashes :meth:`verify_and_update` should
            flag for rehashing. The sentinel ``"auto"`` deprecates every scheme
            except the primary one.
        :param _autoload: accepted for passlib API compatibility and ignored;
            there are no backend handlers to load.
        :param kwargs: passlib-style options. Only ``pbkdf2_sha512__rounds`` is
            honoured; any other key is ignored.
        """
        self._schemes = list(schemes) if schemes else ["pbkdf2_sha512"]
        self._deprecated = set(deprecated) if deprecated else set()
        self._rounds = kwargs.get("pbkdf2_sha512__rounds", _DEFAULT_ROUNDS)

    def hash(self, password: str) -> str:
        """Hash a password using the primary scheme (pbkdf2_sha512)."""
        return pbkdf2_sha512_hash(password, self._rounds)

    def verify(self, password: str, hash_str: str) -> bool:
        """Verify a password against a hash."""
        parsed = _parse_hash(hash_str)
        if parsed:
            rounds, salt, expected = parsed
            actual = _pbkdf2_sha512(password, salt, rounds)
            return hmac.compare_digest(actual, expected)
        if self.identify(hash_str) == "pbkdf2_sha512":
            return False
        if "plaintext" in self._schemes:
            return hmac.compare_digest(
                password.encode("utf-8"), hash_str.encode("utf-8")
            )
        return False

    def verify_and_update(
        self, password: str, hash_str: str
    ) -> tuple[bool, str | None]:
        """Verify password and return (valid, replacement_hash_or_None).

        The replacement is a freshly computed hash if the current one uses deprecated
        settings (wrong scheme or different round count), else None.
        """
        if not self.verify(password, hash_str):
            return False, None

        needs_update = False
        scheme = self.identify(hash_str)

        if self._deprecated:
            if "auto" in self._deprecated:
                if scheme != self._schemes[0]:
                    needs_update = True
            elif scheme in self._deprecated:
                needs_update = True

        if scheme == "pbkdf2_sha512" and not needs_update:
            parsed = _parse_hash(hash_str)
            if parsed and parsed[0] != self._rounds:
                needs_update = True

        replacement = self.hash(password) if needs_update else None
        return True, replacement

    def identify(self, hash_str: str) -> str:
        """Identify the scheme used in a hash string."""
        if hash_str and hash_str.startswith("$pbkdf2-sha512$"):
            return "pbkdf2_sha512"
        return "plaintext"

    def schemes(self) -> list[str]:
        """Return list of configured schemes."""
        return list(self._schemes)

    def update(self, **kwargs: object) -> None:
        """Update context configuration."""
        if "schemes" in kwargs:
            schemes = kwargs["schemes"]
            if isinstance(schemes, str):
                schemes = [schemes]
            assert all(isinstance(s, str) for s in schemes)
            self._schemes = list(schemes)
        if "deprecated" in kwargs:
            dep = kwargs["deprecated"]
            self._deprecated = set(dep) if dep else set()
        if "pbkdf2_sha512__rounds" in kwargs:
            self._rounds = kwargs["pbkdf2_sha512__rounds"]

    def copy(self) -> CryptContext:
        """Create a copy of this context with the same configuration."""
        ctx = CryptContext.__new__(CryptContext)
        ctx._schemes = list(self._schemes)
        ctx._deprecated = set(self._deprecated)
        ctx._rounds = self._rounds
        return ctx
