import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg.errors

if TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.http import Stream

_logger = logging.getLogger(__name__)

STORAGE_BACKENDS: dict[str, type[AttachmentStorage]] = {}

_UNKNOWN_SCHEMES_WARNED: set[tuple[str, str]] = set()


def register_storage(cls: type[AttachmentStorage]) -> type[AttachmentStorage]:
    if not cls.location:
        msg = f"{cls.__name__} must define a location name to be registered"
        raise ValueError(msg)
    if (current := STORAGE_BACKENDS.get(cls.location)) not in (None, cls):
        msg = (
            f"storage location {cls.location!r} is already registered by "
            f"{current.__name__}; {cls.__name__} cannot claim it too"
        )
        raise ValueError(msg)
    STORAGE_BACKENDS[cls.location] = cls
    return cls


def backend_for_key(env: Environment, key: str) -> AttachmentStorage:
    if "://" in key:
        for backend_cls in STORAGE_BACKENDS.values():
            if backend_cls.owns_key(key):
                return backend_cls(env)
        scheme = key.split("://", 1)[0]
        if (seen_key := (env.cr.dbname, scheme)) not in _UNKNOWN_SCHEMES_WARNED:
            _UNKNOWN_SCHEMES_WARNED.add(seen_key)
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
    location: str = ""
    key_scheme: str = ""

    def __init__(self, env: Environment) -> None:
        self.env = env

    @classmethod
    def owns_key(cls, key: str) -> bool:
        return bool(cls.key_scheme) and key.startswith(cls.key_scheme + "://")

    @staticmethod
    def _inline_datas_values(data: bytes) -> dict[str, Any]:
        return {"store_fname": False, "db_datas": data}

    def write(self, data: bytes, checksum: str) -> dict[str, Any]:
        raise NotImplementedError

    def write_stream(self, fileobj: Any) -> dict[str, Any]:
        model = self.env["ir.attachment"]
        data = fileobj.read()
        if isinstance(data, str):
            data = data.encode()
        checksum = model._get_content_checksum(data)
        return {
            "checksum": checksum,
            "file_size": len(data),
            **self.write(data, checksum),
        }

    def migration_domain(self) -> list:
        raise NotImplementedError

    def read(self, key: str, size: int | None = None) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def to_stream(self, attachment: Any, stream: Stream) -> Stream:
        raise NotImplementedError

    def autovacuum(self) -> bool | None:
        pass


@register_storage
class DbStorage(AttachmentStorage):
    location = "db"

    def write(self, data: bytes, checksum: str) -> dict[str, Any]:
        return self._inline_datas_values(data)

    def migration_domain(self) -> list[tuple[str, str, Any]]:
        return [("store_fname", "!=", False)]


@register_storage
class FileStorage(AttachmentStorage):
    location = "file"

    def _model(self):
        return self.env["ir.attachment"]

    def write(self, data: bytes, checksum: str) -> dict[str, Any]:
        if not data:
            return self._inline_datas_values(data)
        return {
            "store_fname": self._model()._write_file(data, checksum),
            "db_datas": False,
        }

    def write_stream(self, fileobj: Any) -> dict[str, Any]:
        fname, size, checksum = self._model()._write_file_stream(fileobj)
        if not size:
            return {
                "checksum": checksum,
                "file_size": 0,
                **self._inline_datas_values(b""),
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
        return self._model()._read_file(key, size=size)

    def delete(self, key: str) -> None:
        self._model()._mark_for_gc(key)

    def autovacuum(self) -> bool | None:
        model = self._model()
        cr = self.env.cr
        cr.commit()

        checklist = model._get_gc_checklist(limit=model._GC_MAX_ENTRIES)
        if len(checklist) >= model._GC_MAX_ENTRIES:
            _logger.info(
                "filestore gc: checklist cap reached (%d entries); the "
                "remainder will be swept by the next run",
                len(checklist),
            )

        cr.execute("SET LOCAL lock_timeout TO '10s'")
        try:
            cr.execute("LOCK ir_attachment IN SHARE MODE")
        except psycopg.errors.LockNotAvailable:
            cr.rollback()
            return False

        model._gc_file_store_unsafe(checklist)

        cr.commit()
        return None

    def to_stream(self, attachment: Any, stream: Stream) -> Stream:
        stream.type = "path"
        try:
            stream.path = attachment._get_full_path(attachment.store_fname)
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
            stream.type = "data"
            stream.data = b""
            stream.size = 0
            stream.etag = False
            stream.last_modified = None
            stream.conditional = False
            stream.public = False
            return stream
        stream.last_modified = stat.st_mtime
        stream.size = stat.st_size
        return stream
