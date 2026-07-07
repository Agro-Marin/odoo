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


def register_storage(cls: type[AttachmentStorage]) -> type[AttachmentStorage]:
    """Class decorator registering *cls* under its ``location`` name."""
    assert cls.location, "storage backend must define a location name"
    STORAGE_BACKENDS[cls.location] = cls
    return cls


def backend_for_key(env: Environment, key: str) -> AttachmentStorage:
    """Return the read-side backend owning *key*.

    Dispatch is by URI scheme; keys without a scheme (the plain
    ``ab/<sha1>`` sharded layout) belong to the local filestore.

    :param env: the current environment
    :param str key: a ``store_fname`` value
    :rtype: AttachmentStorage
    """
    if "://" in key:
        for backend_cls in STORAGE_BACKENDS.values():
            if backend_cls.owns_key(key):
                return backend_cls(env)
    return FileStorage(env)


class AttachmentStorage:
    """Contract for an ir.attachment content storage backend.

    Scope — which extension axis to pick
    ------------------------------------

    This registry is for **content-addressed key stores**: backends that
    persist opaque payloads under a store key (``store_fname``) and serve
    them back through Odoo (:meth:`read` / :meth:`to_stream`) — the local
    filestore, the db column, an S3-like blob store fronted by the server.
    Register a subclass with ``@register_storage``; write-side dispatch
    follows the ``ir_attachment.location`` parameter, read-side dispatch
    follows the key's URI scheme (:func:`backend_for_key`).

    **URL-redirect storage is deliberately NOT this axis.** Attachments
    whose content the *client* exchanges directly with a remote store
    (signed upload/download URLs, CDN) remain the sanctioned domain of the
    ``cloud_storage`` module and its provider add-ons (``type='cloud_storage'``
    rows driven by the ``cloud_storage_provider`` parameter, with
    ``_to_http_stream`` / ``_generate_cloud_storage_*`` overrides — see
    ``odoo/addons/cloud_storage`` and the agromarin ``ir_attachment_s3``
    extension). Those rows carry a ``url``, not a store key, so they never
    reach this registry. Pick the axis by who serves the bytes: Odoo
    serves them → register a backend here; the client talks to the remote
    store directly → extend ``cloud_storage``.
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
        """Content-location fragment keeping *data* inline in ``db_datas``.

        The shared no-store-key case: db storage, and EMPTY content on any
        backend (an empty payload is never keyed externally — no file, no
        blob — it stays inline on the row, see :meth:`FileStorage.write`).
        """
        return {"store_fname": False, "db_datas": data}

    def write(self, data: bytes, checksum: str) -> dict[str, Any]:
        """Persist *data* in the backend and return its store values.

        :param bytes data: the binary content
        :param str checksum: SHA-1 hex digest of *data*
        :return: the ``store_fname`` / ``db_datas`` values to persist on
            the row. The persisted key comes from the write itself — the
            single source of truth for where the content lives (there is
            deliberately no separate "derive the key" hook to keep in sync
            with what was actually written). Backends that keep content
            inline (db storage, empty content) return the inline fragment
            (:meth:`_inline_datas_values`) without external I/O.
        :rtype: dict
        """
        raise NotImplementedError

    def write_stream(self, fileobj: Any) -> dict[str, Any]:
        """Persist the content read from *fileobj* and return its store values.

        Default implementation BUFFERS the whole stream then delegates to
        :meth:`write` — backends that can stream (see :class:`FileStorage`)
        override this to keep peak memory flat. Backends that cannot stream
        (``db``, custom column stores) inherit the buffering, preserving the
        previous behavior.

        :param fileobj: a binary file-like supporting ``read(size)``
        :return: the create/write columns to persist (``store_fname`` /
            ``db_datas`` / ``checksum`` / ``file_size``)
        :rtype: dict
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

        Used by ``force_storage`` to find the rows to migrate INTO this
        backend. A keyed custom backend must match both db rows and other
        backends' keys (see ``MemoryStorage`` in the tests for an example).
        The file backend keeps its historical ``db_datas`` domain, which
        does not claim other backends' keys — custom→file migration is a
        known limitation, by design.
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
        # Only keyed content reaches this hook: _to_http_stream dispatches by
        # store key, and db-/url-backed rows have no key to dispatch on — they
        # are served inline there. A keyed backend (file, s3, ...) MUST
        # implement this.
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
        # Continue in a new transaction. The LOCK statement below must be the
        # first one in the current transaction, otherwise the database snapshot
        # used by it may not contain the most recent changes made to the table
        # ir_attachment! Indeed, if concurrent transactions create attachments,
        # the LOCK statement will wait until those concurrent transactions end.
        # But this transaction will not see the new attachments if it has done
        # other requests before the LOCK (like reading the storage location).
        cr = self.env.cr
        cr.commit()

        # Scan the checklist (filesystem, no DB) BEFORE locking, so the table
        # lock only spans the whitelist query + unlinks, not the directory walk.
        # The walk has no DB effect, so the LOCK is still the first DB statement
        # of the new transaction (snapshot freshness, see comment above).
        # The scan is capped (_GC_MAX_ENTRIES): the whole sweep below runs
        # under the SHARE MODE lock, during which every attachment write
        # blocks — after a bulk delete an unbounded checklist would hold that
        # lock for the full backlog. Entries past the cap stay on disk and are
        # picked up by the next run.
        checklist = model._gc_checklist(limit=model._GC_MAX_ENTRIES)
        if len(checklist) >= model._GC_MAX_ENTRIES:
            _logger.info(
                "filestore gc: checklist cap reached (%d entries); the "
                "remainder will be swept by the next run",
                len(checklist),
            )

        # prevent all concurrent updates on ir_attachment while collecting,
        # but only attempt to grab the lock for a little bit, otherwise it'd
        # start blocking other transactions. (will be retried later anyway)
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
        # Single-source the filestore traversal invariant through the model's
        # _full_path (sanitize + resolve + containment) instead of a parallel
        # safe_join. _full_path uses the cursor's db (== request.db under HTTP,
        # and correct on the no-request cron/report path) and raises on an
        # escaping key; treat that like a missing file below.
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
            # Fall back to empty data so the caller gets a valid stream
            # instead of an unhandled 500 error.
            stream.type = "data"
            stream.data = b""
            stream.size = 0
            # Neutralize the caching metadata: _to_http_stream built the
            # stream with etag = checksum — the REAL content's digest — so a
            # 200 with this empty body would be cached by browsers/proxies
            # under the real ETag. Once the filestore file is restored,
            # conditional requests keep matching that ETag, get 304, and
            # clients keep the empty body forever. Serve the degraded
            # response uncacheable and unconditional instead.
            stream.etag = False
            stream.last_modified = None
            stream.conditional = False
            stream.public = False
            return stream
        stream.last_modified = stat.st_mtime
        stream.size = stat.st_size
        return stream
