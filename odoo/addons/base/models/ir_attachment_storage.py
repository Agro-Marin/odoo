import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg.errors

if TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.http import Stream

_logger = logging.getLogger(__name__)

# {location_name: backend class} — write-side registry
STORAGE_BACKENDS: dict[str, type[AttachmentStorage]] = {}

# Schemes already reported by backend_for_key's no-backend warning, so a
# missing backend is logged once per scheme per process, not once per read
# (orphaned s3:// keys would otherwise flood the log).
_UNKNOWN_SCHEMES_WARNED: set[str] = set()


def register_storage(cls: type[AttachmentStorage]) -> type[AttachmentStorage]:
    """Class decorator registering *cls* under its ``location`` name."""
    assert cls.location, "storage backend must define a location name"
    STORAGE_BACKENDS[cls.location] = cls
    return cls


def backend_for_key(env: Environment, key: str) -> AttachmentStorage:
    """Return the read-side backend owning *key*, dispatched by URI scheme.

    Keys without a scheme (the plain ``ab/<sha1>`` sharded layout) belong to
    the local filestore. A schemed key whose backend is NOT registered (e.g.
    ``s3://`` rows left after uninstalling the backend) also falls back to the
    filestore, but warns once per scheme so the inevitable read failure is
    blamed on the missing backend, not the filestore.
    """
    if "://" in key:
        for backend_cls in STORAGE_BACKENDS.values():
            if backend_cls.owns_key(key):
                return backend_cls(env)
        scheme = key.split("://", 1)[0]
        if scheme not in _UNKNOWN_SCHEMES_WARNED:
            _UNKNOWN_SCHEMES_WARNED.add(scheme)
            _logger.warning(
                "No storage backend registered for scheme %r (key %r); "
                "falling back to the local filestore. Subsequent read "
                "failures for such keys are caused by the missing backend "
                "module, not the filestore. (warned once per scheme)",
                scheme,
                key,
            )
    return FileStorage(env)


class AttachmentStorage:
    """Contract for an ir.attachment content storage backend.

    For **content-addressed key stores**: backends that persist opaque payloads
    under a store key (``store_fname``) and serve them back through Odoo
    (:meth:`read` / :meth:`to_stream`) — local filestore, db column, an S3-like
    blob store fronted by the server. Register a subclass with
    ``@register_storage``; write-side dispatch follows the
    ``ir_attachment.location`` parameter, read-side dispatch follows the key's
    URI scheme (:func:`backend_for_key`).

    URL-redirect storage is deliberately NOT this axis: attachments whose
    content the *client* exchanges directly with a remote store (signed URLs,
    CDN) belong to the ``cloud_storage`` module — those rows carry a ``url``,
    not a store key, so they never reach this registry. Pick by who serves the
    bytes: Odoo serves them → register here; the client talks to the store
    directly → extend ``cloud_storage``.
    """

    # write-side registry name (the ``ir_attachment.location`` value)
    location: str = ""
    # URI scheme prefixing this backend's store keys; empty = no keyed
    # content (db) or plain keys (file, the no-scheme fallback)
    key_scheme: str = ""

    def __init__(self, env: Environment) -> None:
        self.env = env

    @classmethod
    def owns_key(cls, key: str) -> bool:
        """Return whether *key* is a store key managed by this backend."""
        return bool(cls.key_scheme) and key.startswith(cls.key_scheme + "://")

    # -- write side (dispatched by configured location) ------------------

    @staticmethod
    def _inline_datas_values(data: bytes) -> dict[str, Any]:
        """Store values keeping *data* inline in ``db_datas`` (no store key).

        The shared no-key case: db storage, and empty content on any backend
        (an empty payload is never keyed externally — see
        :meth:`FileStorage.write`).
        """
        return {"store_fname": False, "db_datas": data}

    def write(self, data: bytes, checksum: str) -> dict[str, Any]:
        """Persist *data* and return the ``store_fname`` / ``db_datas`` values.

        The store key is a by-product of the write itself (no separate
        "derive the key" hook to keep in sync). Backends that keep content
        inline (db, empty content) return the inline fragment
        (:meth:`_inline_datas_values`) without external I/O.

        :param str checksum: SHA-1 hex digest of *data*
        """
        raise NotImplementedError

    def write_stream(self, fileobj: Any) -> dict[str, Any]:
        """Persist the content of *fileobj* and return its store values.

        Default buffers the whole stream then delegates to :meth:`write`.
        Backends that can stream (see :class:`FileStorage`) override this to
        keep peak memory flat; non-streaming backends (``db``) inherit the
        buffering.

        :param fileobj: a binary file-like supporting ``read(size)``
        :return: columns to persist (``store_fname`` / ``db_datas`` /
            ``checksum`` / ``file_size``)
        """
        model = self.env["ir.attachment"]
        data = fileobj.read()
        if isinstance(data, str):
            data = data.encode()
        checksum = model._content_checksum(data)
        return {
            "checksum": checksum,
            "file_size": len(data),
            **self.write(data, checksum),
        }

    def migration_domain(self) -> list:
        """Return the domain matching attachments NOT in this backend.

        Used by ``force_storage`` to find rows to migrate INTO this backend.
        A keyed custom backend must match both db rows and other backends'
        keys. The file backend keeps its historical ``db_datas`` domain, which
        does not claim other backends' keys — custom→file migration is a known
        limitation, by design.
        """
        raise NotImplementedError

    # -- read side (dispatched by store key, see backend_for_key) --------

    def read(self, key: str, size: int | None = None) -> bytes:
        """Read up to *size* bytes (all if ``None``) of the content at *key*."""
        raise NotImplementedError

    def delete(self, key: str) -> None:
        """Schedule the content at *key* for deletion (may be deferred)."""
        raise NotImplementedError

    def to_stream(self, attachment: Any, stream: Stream) -> Stream:
        """Fill *stream* to serve *attachment*'s keyed content over HTTP."""
        # Only keyed content reaches this hook (_to_http_stream serves db-/url-
        # backed rows inline). A keyed backend (file, s3, ...) MUST implement it.
        raise NotImplementedError

    # -- maintenance ------------------------------------------------------

    def autovacuum(self) -> bool | None:
        """Garbage-collect content no longer referenced by any attachment.

        :return: ``False`` when the run was skipped and should be retried
            on the next autovacuum, else ``None``
        """


@register_storage
class DbStorage(AttachmentStorage):
    """Content stored in the ``db_datas`` column; owns no store keys."""

    location = "db"

    def write(self, data: bytes, checksum: str) -> dict[str, Any]:
        # content is persisted by the db_datas column itself
        return self._inline_datas_values(data)

    def migration_domain(self) -> list[tuple[str, str, Any]]:
        return [("store_fname", "!=", False)]


@register_storage
class FileStorage(AttachmentStorage):
    """Content-addressed local filestore (``<shard>/<sha1>`` keys).

    I/O delegates to the model's ``_file_*`` primitives: they are the
    historical override surface and several test suites patch them
    directly — this class adds the strategy layer, not new I/O.
    """

    location = "file"

    def _model(self):
        """Return the ir.attachment model bound to this backend's env."""
        return self.env["ir.attachment"]

    def write(self, data: bytes, checksum: str) -> dict[str, Any]:
        if not data:
            # empty content stays inline, like db storage (no file written)
            return self._inline_datas_values(data)
        return {
            # the persisted key is _file_write's return value — no parallel
            # re-derivation that must agree with what was actually written
            "store_fname": self._model()._file_write(data, checksum),
            "db_datas": False,
        }

    def write_stream(self, fileobj: Any) -> dict[str, Any]:
        # True streaming: chunked copy + incremental hash, no full buffer.
        fname, size, checksum = self._model()._file_write_stream(fileobj)
        if not size:
            # empty content stays inline, like the buffered write() path
            return {
                "checksum": checksum,
                "file_size": 0,
                "store_fname": False,
                "db_datas": b"",
            }
        return {
            "checksum": checksum,
            "file_size": size,
            "store_fname": fname,
            "db_datas": False,
        }

    def migration_domain(self) -> list[tuple[str, str, Any]]:
        return [("db_datas", "!=", False)]

    def read(self, key: str, size: int | None = None) -> bytes:
        # keyword arg: _file_read is a documented test-patch surface and
        # several suites assert on the spied call's `size=` kwarg
        return self._model()._file_read(key, size=size)

    def delete(self, key: str) -> None:
        self._model()._file_delete(key)

    def autovacuum(self) -> bool | None:
        """Sweep the GC checklist under a table lock (see _mark_for_gc)."""
        model = self._model()
        # New transaction: the LOCK below must be its first statement, else the
        # snapshot may miss concurrent attachment creates (the LOCK waits for
        # them to end, but a transaction that already ran other queries won't
        # see their rows).
        cr = self.env.cr
        cr.commit()

        # Scan the checklist (filesystem, no DB) BEFORE locking, so the lock
        # spans only the whitelist query + unlinks, and stays the first DB
        # statement (snapshot freshness, above). The scan is capped
        # (_GC_MAX_ENTRIES): the sweep runs under the SHARE MODE lock, blocking
        # every attachment write — an unbounded checklist would hold it for the
        # whole backlog. Entries past the cap wait for the next run.
        checklist = model._gc_checklist(limit=model._GC_MAX_ENTRIES)
        if len(checklist) >= model._GC_MAX_ENTRIES:
            _logger.info(
                "filestore gc: checklist cap reached (%d entries); the "
                "remainder will be swept by the next run",
                len(checklist),
            )

        # Block concurrent updates on ir_attachment while collecting, but wait
        # only briefly for the lock so we don't block other transactions
        # (retried later anyway).
        cr.execute("SET LOCAL lock_timeout TO '10s'")
        try:
            cr.execute("LOCK ir_attachment IN SHARE MODE")
        except psycopg.errors.LockNotAvailable:
            cr.rollback()
            return False

        model._gc_file_store_unsafe(checklist)

        # commit to release the lock
        cr.commit()
        return None

    def to_stream(self, attachment: Any, stream: Stream) -> Stream:
        stream.type = "path"
        # Route the traversal check through the model's _full_path (sanitize +
        # resolve + containment) rather than a parallel safe_join. It uses the
        # cursor's db (correct under HTTP and on cron/report paths) and raises
        # on an escaping key; treat that like a missing file below.
        try:
            stream.path = attachment._full_path(attachment.store_fname)
        except ValueError:
            stream.path = None
        stat = None
        if stream.path:
            with contextlib.suppress(FileNotFoundError):
                stat = Path(stream.path).stat()
        if stat is None:
            _logger.warning(
                "Filestore file missing or invalid for attachment %s: %s",
                attachment.id,
                stream.path or attachment.store_fname,
            )
            # Fall back to empty data so the caller gets a valid stream, not a 500.
            stream.type = "data"
            stream.data = b""
            stream.size = 0
            # Neutralize caching: the stream's etag is the REAL content digest,
            # so a cached empty body would keep matching it (304) even after the
            # file is restored, serving empty forever. Make it uncacheable.
            stream.etag = False
            stream.last_modified = None
            stream.conditional = False
            stream.public = False
            return stream
        stream.last_modified = stat.st_mtime
        stream.size = stat.st_size
        return stream
