"""Phase-1 tests for the ir.attachment storage-backend skeleton.

Cover write-side backend selection, read-side key dispatch, and equivalence
of backend value fragments with the live model. See the C1 plan
(``2026-06-10-storage-backend-formalization-plan.md``).
"""

import base64
import contextlib
from unittest.mock import patch

import psycopg.errors

from odoo.fields import Domain
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base.models import ir_attachment_storage
from odoo.addons.base.models.ir_attachment_storage import (
    STORAGE_BACKENDS,
    AttachmentStorage,
    DbStorage,
    FileStorage,
    register_storage,
)


class TestIrAttachmentStorage(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]
        self.icp = self.env["ir.config_parameter"]

    def test_location_selection(self):
        """Write-side backend follows ir_attachment.location; unknown → file."""
        self.assertIsInstance(self.Attachment._storage_backend(), FileStorage)
        self.icp.set_param("ir_attachment.location", "db")
        self.assertIsInstance(self.Attachment._storage_backend(), DbStorage)
        self.icp.set_param("ir_attachment.location", "s3")
        self.assertIsInstance(self.Attachment._storage_backend(), FileStorage)

    def test_key_dispatch(self):
        """Read-side backend follows the store key's URI scheme."""
        plain = self.Attachment._backend_for_key("ab/abcdef0123")
        self.assertIsInstance(plain, FileStorage)
        # unregistered scheme falls back to the local filestore (and warns
        # once per scheme — see test_unknown_scheme_warns_once)
        self.addCleanup(ir_attachment_storage._UNKNOWN_SCHEMES_WARNED.discard, "weird")
        with mute_logger("odoo.addons.base.models.ir_attachment_storage"):
            unknown = self.Attachment._backend_for_key("weird://bucket/key")
        self.assertIsInstance(unknown, FileStorage)

        class FakeS3Storage(AttachmentStorage):
            location = "fake_s3"
            key_scheme = "fake-s3"

        register_storage(FakeS3Storage)
        try:
            owned = self.Attachment._backend_for_key("fake-s3://bucket/key")
            self.assertIsInstance(owned, FakeS3Storage)
            # registration also enables write-side selection
            self.icp.set_param("ir_attachment.location", "fake_s3")
            self.assertIsInstance(self.Attachment._storage_backend(), FakeS3Storage)
        finally:
            STORAGE_BACKENDS.pop("fake_s3")

    def test_unknown_scheme_warns_once(self):
        """IRA-S2: a schemed key with no registered backend falls back to the
        filestore with a distinct warning, once per scheme, so the read
        failure is blamed on the missing backend, not the filestore.
        """
        self.addCleanup(
            ir_attachment_storage._UNKNOWN_SCHEMES_WARNED.discard, "ghost-s3"
        )
        with self.assertLogs(
            "odoo.addons.base.models.ir_attachment_storage", level="WARNING"
        ) as cm:
            backend = self.Attachment._backend_for_key("ghost-s3://bucket/key")
        self.assertIsInstance(backend, FileStorage)
        self.assertEqual(len(cm.records), 1)
        message = cm.records[0].getMessage()
        self.assertIn("No storage backend registered", message)
        self.assertIn("ghost-s3", message)
        # Second read of the same scheme: silent (once-per-scheme dedup).
        with patch.object(ir_attachment_storage._logger, "warning") as warn:
            again = self.Attachment._backend_for_key("ghost-s3://bucket/other")
        self.assertIsInstance(again, FileStorage)
        warn.assert_not_called()

    def test_stream_key_dispatch(self):
        """_to_http_stream routes keyed content to the key's owning backend."""
        att = self.Attachment.create({"name": "ks.bin", "raw": b"ks-payload"})

        class FakeStreamStorage(AttachmentStorage):
            location = "fake_stream"
            key_scheme = "fake-stream"

            def to_stream(self, attachment, stream):
                stream.type = "url"
                stream.url = "fake://served"
                return stream

        register_storage(FakeStreamStorage)
        try:
            self.env.cr.execute(
                "UPDATE ir_attachment SET store_fname = %s WHERE id = %s",
                ["fake-stream://bucket/key", att.id],
            )
            att.invalidate_recordset()
            stream = att._to_http_stream()
            self.assertEqual((stream.type, stream.url), ("url", "fake://served"))
        finally:
            STORAGE_BACKENDS.pop("fake_stream")

    def test_write_fragment_matches_model(self):
        """backend.write's store fragment equals _get_datas_related_values output."""
        for location, backend_cls in (("file", FileStorage), ("db", DbStorage)):
            self.icp.set_param("ir_attachment.location", location)
            for data in (b"payload", b""):
                with self.subTest(location=location, data=data):
                    model_vals = self.Attachment._get_datas_related_values(
                        data, "text/plain"
                    )
                    checksum = self.Attachment._content_checksum(data)
                    fragment = backend_cls(self.env).write(data, checksum)
                    self.assertEqual(fragment["store_fname"], model_vals["store_fname"])
                    self.assertEqual(fragment["db_datas"], model_vals["db_datas"])

    def test_gc_lock_not_available_returns_false(self):
        """A lock timeout skips the sweep and reports False for retry."""
        real_execute = self.env.cr.execute

        def fake_execute(query, *args, **kwargs):
            if str(query).startswith("LOCK ir_attachment"):
                raise psycopg.errors.LockNotAvailable("simulated lock timeout")
            return real_execute(query, *args, **kwargs)

        # commit/rollback are forbidden in tests; stub them to test the
        # control flow around the lock failure
        with (
            patch.object(self.env.cr, "commit", lambda: None),
            patch.object(self.env.cr, "rollback", lambda: None),
            patch.object(self.env.cr, "execute", side_effect=fake_execute),
        ):
            result = FileStorage(self.env).autovacuum()
        self.assertIs(result, False)
        # the hook propagates the skip signal
        with (
            patch.object(self.env.cr, "commit", lambda: None),
            patch.object(self.env.cr, "rollback", lambda: None),
            patch.object(self.env.cr, "execute", side_effect=fake_execute),
        ):
            self.assertIs(self.Attachment._gc_file_store(), False)

    def test_migration_domain_delegation(self):
        """_get_storage_domain delegates per configured backend."""
        cases = (
            ("file", [("db_datas", "!=", False)]),
            ("db", [("store_fname", "!=", False)]),
            ("s3", [("db_datas", "!=", False)]),  # unknown → file-like
        )
        for location, expected in cases:
            with self.subTest(location=location):
                self.icp.set_param("ir_attachment.location", location)
                self.assertEqual(self.Attachment._get_storage_domain(), expected)


class MemoryStorage(AttachmentStorage):
    """In-memory backend: the test seam proving the contract is complete.

    Deletes are reference-counted against ``store_fname`` (like the file
    backend's deferred GC): content-addressed keys are shared by copies, so
    an eager delete would corrupt remaining references.
    """

    location = "memory"
    key_scheme = "mem"
    blobs: dict[str, bytes] = {}

    def _key(self, checksum: str) -> str:
        return f"mem://{checksum}"

    def write(self, data, checksum):
        # persist AND return the store fragment in one step (empty content
        # stays inline, like the file/db backends)
        if not data:
            return self._inline_datas_values(data)
        key = self._key(checksum)
        type(self).blobs[key] = bytes(data)
        return {"store_fname": key, "db_datas": False}

    def read(self, key, size=None):
        data = type(self).blobs.get(key, b"")
        return data if size is None else data[:size]

    def delete(self, key):
        # drop only when no attachment still references the key (callers
        # flush before deleting old keys, so the SQL state is current)
        self.env.cr.execute(
            "SELECT 1 FROM ir_attachment WHERE store_fname = %s LIMIT 1", [key]
        )
        if not self.env.cr.fetchone():
            type(self).blobs.pop(key, None)

    def to_stream(self, attachment, stream):
        data = self.read(attachment.store_fname)
        stream.type = "data"
        stream.data = data
        stream.size = len(data)
        stream.last_modified = attachment.write_date
        return stream

    def migration_domain(self):
        # rows NOT in this backend: db rows, plus other backends' keys
        return [
            "|",
            ("db_datas", "!=", False),
            "&",
            ("store_fname", "!=", False),
            ("store_fname", "not like", "mem://%"),
        ]


@contextlib.contextmanager
def activate_memory_storage(env):
    """Register MemoryStorage and make it the configured write backend."""
    register_storage(MemoryStorage)
    env["ir.config_parameter"].set_param("ir_attachment.location", "memory")
    try:
        yield MemoryStorage
    finally:
        STORAGE_BACKENDS.pop("memory", None)
        MemoryStorage.blobs.clear()
        env["ir.config_parameter"].set_param("ir_attachment.location", "file")


class TestMemoryStorageCRUD(TransactionCase):
    """CRUD flows against a non-file backend prove the contract is complete.

    Not the whole attachment suite: tests asserting filestore specifics
    (on-disk paths, GC checklist) stay on FileStorage.
    """

    def test_crud_lifecycle(self):
        payload = b"mem-payload"
        with activate_memory_storage(self.env):
            Attachment = self.env["ir.attachment"]
            att = Attachment.create(
                {"name": "m.txt", "raw": payload, "mimetype": "text/plain"}
            )
            self.assertTrue(att.store_fname.startswith("mem://"))
            self.assertFalse(att.db_datas)

            att.invalidate_recordset()
            self.assertEqual(att.raw, payload)
            self.assertEqual(att.datas, base64.b64encode(payload))

            stream = att._to_http_stream()
            self.assertEqual((stream.type, stream.data), ("data", payload))

            # copy relinks the key without reading content
            copy = att.copy()
            self.assertEqual(copy.store_fname, att.store_fname)
            copy.invalidate_recordset()
            self.assertEqual(copy.raw, payload)

            # rewriting the original must not destroy the copy's shared blob
            att.write({"raw": b"mem-rewritten"})
            att.invalidate_recordset()
            self.assertEqual(att.raw, b"mem-rewritten")
            copy.invalidate_recordset()
            self.assertEqual(copy.raw, payload)

            # last reference gone -> blob collected
            old_key = copy.store_fname
            copy.unlink()
            self.assertNotIn(old_key, MemoryStorage.blobs)

    def test_force_storage_migrates_into_memory(self):
        payload = b"fs-to-mem-payload"
        att = self.env["ir.attachment"].create({"name": "fs.bin", "raw": payload})
        self.assertNotIn("://", att.store_fname)
        with activate_memory_storage(self.env):
            # Do NOT run a filestore-wide force_storage() here: _migrate marks
            # every live store_fname for GC on disk — a non-transactional side
            # effect that survives the rollback and can wipe filestore files
            # still referenced by the DB (observed 2026-07-07). Assert the
            # search domain would pick the attachment, then migrate only it.
            candidates = (
                self.env["ir.attachment"]
                .with_context(skip_res_field_check=True)
                .search(
                    Domain.AND(
                        [
                            self.env["ir.attachment"]._get_storage_domain(),
                            [("type", "=", "binary"), ("id", "=", att.id)],
                        ]
                    )
                )
            )
            self.assertEqual(candidates, att)
            candidates._migrate()
            att.invalidate_recordset()
            self.assertTrue(att.store_fname.startswith("mem://"))
            self.assertEqual(att.raw, payload)

    def test_unreadable_content_copy_preserves_metadata(self):
        """Copy preserves metadata even when backend content is unreadable
        (IRA-B4, the A1 scenario simulated without monkeypatching privates, E1)."""
        payload = b"e1-payload"
        with activate_memory_storage(self.env):
            att = self.env["ir.attachment"].create({"name": "e1.bin", "raw": payload})
            MemoryStorage.blobs.clear()  # simulate lost backend content
            att.invalidate_recordset()
            self.assertEqual(att.raw, b"")  # read failure is visible
            copy = att.copy()  # ...and copies preserve metadata, not emptiness
            self.assertEqual(copy.file_size, len(payload))
            self.assertEqual(copy.store_fname, att.store_fname)
