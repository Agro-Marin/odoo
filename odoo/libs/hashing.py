"""Content hashing primitives: BLAKE3 when available, stdlib fallback otherwise.

BLAKE3 is markedly faster than the stdlib digests on the payload sizes that
dominate here — measured on this fork (64 MiB, one core unless noted)::

    sha1     1866 MB/s    sha256   1578 MB/s    blake2b   783 MB/s
    blake3   3447 MB/s    blake3 (max_threads=AUTO)   15849 MB/s

The crossover is around 1 KiB: below it the extension-call overhead makes
BLAKE3 *slower* than sha1 (0.48 vs 0.33 us on 64 B), so callers hashing short
strings should keep using ``hashlib`` directly rather than reach for this
module.

Two families, because the two uses have different fallbacks and different
failure modes:

- ``content_*`` — content addressing and dedup keys (``ir.attachment``).
  Falls back to **sha1**, the historical digest for those keys.
- ``cache_*`` — cache-key / revalidation digests (asset bundles, module
  checksums, response stamps).  Falls back to **sha256**, the historical
  digest for those.

Keeping each fallback on its historical algorithm means a deployment without
the ``blake3`` wheel reproduces today's digests byte-for-byte instead of
silently rehashing everything.

``blake3`` is a hard requirement (see ``requirements.txt``), but the import is
guarded anyway: the content digest is *persisted* (``ir_attachment.checksum``
and the store key derived from it), so a worker whose extension failed to load
must still be able to read the filestore.  Degrading to sha1 keeps such a node
serving; an ImportError at startup would not.

None of these digests are used for authentication.  Signed tokens, CSRF, API
keys and password hashing stay on HMAC-SHA256 / pbkdf2 (``tools/security.py``,
``http/_csrf.py``, ``tools/password.py``) — BLAKE3's keyed mode would be a fine
primitive there, but swapping it in invalidates every live token, so that is a
separate, versioned change.
"""

import hashlib
from pathlib import Path
from typing import Any

_blake3: Any  # the class when the optional extension is present, else None
try:
    from blake3 import blake3 as _blake3
except ImportError:
    _blake3 = None

__all__ = [
    "ALGO_TAG",
    "CONTENT_DIGEST_LEN",
    "CONTENT_DIGEST_LEN_BY_TAG",
    "CONTENT_DIGEST_MAX_LEN",
    "HAS_BLAKE3",
    "cache_hash",
    "cache_hasher",
    "content_hash",
    "content_hash_file",
    "content_hasher",
    "update_from_file",
]

HAS_BLAKE3 = _blake3 is not None

ALGO_TAG = "b3" if HAS_BLAKE3 else "s1"

CONTENT_DIGEST_LEN_BY_TAG = {"s1": 40, "b3": 64}

CONTENT_DIGEST_LEN = CONTENT_DIGEST_LEN_BY_TAG[ALGO_TAG]

CONTENT_DIGEST_MAX_LEN = 64

if CONTENT_DIGEST_LEN > CONTENT_DIGEST_MAX_LEN:
    raise RuntimeError(
        f"content digest is {CONTENT_DIGEST_LEN} hex chars but the schema "
        f"holds at most {CONTENT_DIGEST_MAX_LEN}: widen "
        "ir_attachment.checksum and migrate existing databases before "
        "switching to a longer algorithm"
    )

_MT_MIN_BYTES = 1 << 20

_FILE_CHUNK = 1 << 20


def _new(mt: bool = False) -> Any:
    return _blake3(max_threads=_blake3.AUTO if mt else 1)


def content_hasher() -> Any:
    """Return an incremental hasher for content addressing (single-threaded).

    Feed it with ``update()`` and read ``hexdigest()``, like a ``hashlib``
    object.  Use this for streaming writes where the payload never exists as
    one ``bytes``; :func:`content_hash` is the one-shot form.
    """
    return _new() if HAS_BLAKE3 else hashlib.sha1(usedforsecurity=False)


def content_hash(data: bytes) -> str:
    """Return the content-digest hex of *data* (BLAKE3, else sha1).

    Multithreaded above :data:`_MT_MIN_BYTES`.
    """
    if not HAS_BLAKE3:
        return hashlib.sha1(data or b"", usedforsecurity=False).hexdigest()
    hasher = _new(mt=len(data) >= _MT_MIN_BYTES)
    hasher.update(data)
    return hasher.hexdigest()


def content_hash_file(path: str | Path) -> str:
    """Return the content-digest hex of the file at *path*.

    BLAKE3 memory-maps the file (no copy into Python), so this stays flat in
    memory regardless of file size; the fallback streams it in chunks.
    """
    if not HAS_BLAKE3:
        digest = hashlib.sha1(usedforsecurity=False)
        with Path(path).open("rb") as fd:
            while chunk := fd.read(_FILE_CHUNK):
                digest.update(chunk)
        return digest.hexdigest()
    hasher = _new(mt=True)
    hasher.update_mmap(str(path))
    return hasher.hexdigest()


def update_from_file(hasher: Any, path: str | Path) -> None:
    """Feed the content of the file at *path* into *hasher*.

    BLAKE3 memory-maps (no copy into Python, empty files included); the
    stdlib fallback streams in chunks.  Works mid-digest, so a caller can
    interleave file content with its own separators.
    """
    if HAS_BLAKE3:
        hasher.update_mmap(str(path))
        return
    with Path(path).open("rb") as fd:
        while chunk := fd.read(_FILE_CHUNK):
            hasher.update(chunk)


def cache_hasher() -> Any:
    """Return an incremental hasher for cache keys (BLAKE3, else sha256)."""
    return _new() if HAS_BLAKE3 else hashlib.sha256()


def cache_hash(data: bytes) -> str:
    """Return the cache-key hex digest of *data* (BLAKE3, else sha256)."""
    if not HAS_BLAKE3:
        return hashlib.sha256(data).hexdigest()
    hasher = _new(mt=len(data) >= _MT_MIN_BYTES)
    hasher.update(data)
    return hasher.hexdigest()
