"""Storage backends for ir.attachment content.

Formalizes the storage strategy that was previously implicit in scattered
``_storage() != "db"`` checks (see plan
``2026-06-10-storage-backend-formalization-plan.md``). Two dispatch axes:

- **Write side** — ``ir_attachment.location`` decides where NEW content
  goes: :meth:`IrAttachment._storage_backend` resolves it from
  ``STORAGE_BACKENDS`` by location name.
- **Read side** — existing content follows the record's store key, NOT the
  configured location (switching the location does not migrate rows):
  :func:`backend_for_key` resolves the owning backend from the key's URI
  scheme (``s3://...``); plain sharded fnames belong to :class:`FileStorage`.

Custom backends subclass :class:`AttachmentStorage` and register with
``@register_storage``. The local-filestore I/O primitives stay on the model
(``_file_read`` / ``_file_write`` / ``_full_path`` / ...): they are a stable
*cross-module API* — other addons call ``attachment._full_path`` /
``_file_read`` directly (``cloud_storage_migration``, ``l10n_mx_edi_payslip``,
``l10n_mx_partner_blocklist``) and ~6 test sites patch them — so
:class:`FileStorage` delegates DOWN to them instead of hosting the I/O itself.
The dependency direction is always backend -> model primitive, never the
reverse (no circularity). Relocating the primitives into this class would
break those consumers; keeping them on the model is a deliberate decision
(2026-06-10 storage-backend-formalization plan, decisions 1 & 3). A *new*
backend needs none of them — see ``MemoryStorage`` in the tests, which
implements the contract self-contained.
"""

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
    """Contract for an ir.attachment content storage backend."""

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

    def datas_values(self, data: bytes, checksum: str) -> dict[str, Any]:
        """Return the content-location fragment for create/write values.

        :param bytes data: the binary content
        :param str checksum: SHA-1 hex digest of *data*
        :return: the ``store_fname`` / ``db_datas`` values to persist
        :rtype: dict
        """
        raise NotImplementedError

    def write(self, data: bytes, checksum: str) -> str | None:
        """Persist *data* in the backend.

        :return: the store key, or ``None`` when nothing was stored
            externally (empty content, or db storage)
        :rtype: str | None
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
        self.write(data, checksum)
        return {
            "checksum": checksum,
            "file_size": len(data),
            **self.datas_values(data, checksum),
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

    def datas_values(self, data: bytes, checksum: str) -> dict[str, Any]:
        return {"store_fname": False, "db_datas": data}

    def write(self, data: bytes, checksum: str) -> str | None:
        # content is persisted by the db_datas column itself
        return None

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

    def datas_values(self, data: bytes, checksum: str) -> dict[str, Any]:
        if not data:
            # empty content stays inline, like db storage (no file written)
            return {"store_fname": False, "db_datas": data}
        return {
            "store_fname": self._model()._file_store_path(checksum),
            "db_datas": False,
        }

    def write(self, data: bytes, checksum: str) -> str | None:
        if not data:
            return None
        return self._model()._file_write(data, checksum)

    def write_stream(self, fileobj: Any) -> dict[str, Any]:
        # True streaming: chunked copy + incremental hash, no full buffer.
        fname, size, checksum = self._model()._file_write_stream(fileobj)
        if not size:
            # empty content stays inline, like the buffered path's datas_values
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
        checklist = model._gc_checklist()

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
            return stream
        stream.last_modified = stat.st_mtime
        stream.size = stat.st_size
        return stream
