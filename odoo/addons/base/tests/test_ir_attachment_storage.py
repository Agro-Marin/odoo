import base64
import contextlib
import io
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
        self.assertIsInstance(self.Attachment._storage_backend(), FileStorage)
        self.icp.set_param("ir_attachment.location", "db")
        self.assertIsInstance(self.Attachment._storage_backend(), DbStorage)
        self.icp.set_param("ir_attachment.location", "s3")
        self.assertIsInstance(self.Attachment._storage_backend(), FileStorage)

    def test_key_dispatch(self):
        plain = self.Attachment._backend_for_key("ab/abcdef0123")
        self.assertIsInstance(plain, FileStorage)
        self.addCleanup(
            ir_attachment_storage._UNKNOWN_SCHEMES_WARNED.discard,
            (self.env.cr.dbname, "weird"),
        )
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
            self.icp.set_param("ir_attachment.location", "fake_s3")
            self.assertIsInstance(self.Attachment._storage_backend(), FakeS3Storage)
        finally:
            STORAGE_BACKENDS.pop("fake_s3")

    def test_unknown_scheme_warns_once(self):
        dbname = self.env.cr.dbname
        self.addCleanup(
            ir_attachment_storage._UNKNOWN_SCHEMES_WARNED.discard, (dbname, "ghost-s3")
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
        with patch.object(ir_attachment_storage._logger, "warning") as warn:
            again = self.Attachment._backend_for_key("ghost-s3://bucket/other")
        self.assertIsInstance(again, FileStorage)
        warn.assert_not_called()

    def test_unknown_scheme_warns_per_database(self):
        dbname = self.env.cr.dbname
        other = f"{dbname}__other"
        for key in ((dbname, "twin-s3"), (other, "twin-s3")):
            self.addCleanup(ir_attachment_storage._UNKNOWN_SCHEMES_WARNED.discard, key)

        with self.assertLogs(
            "odoo.addons.base.models.ir_attachment_storage", level="WARNING"
        ):
            self.Attachment._backend_for_key("twin-s3://bucket/key")

        with (
            patch.object(self.env.cr, "dbname", other),
            self.assertLogs(
                "odoo.addons.base.models.ir_attachment_storage", level="WARNING"
            ) as cm,
        ):
            self.Attachment._backend_for_key("twin-s3://bucket/key")
        self.assertEqual(len(cm.records), 1, "a second database must be told too")

    def test_register_storage_rejects_a_contested_location(self):

        class FirstStorage(AttachmentStorage):
            location = "contested"
            key_scheme = "first"

        class SecondStorage(AttachmentStorage):
            location = "contested"
            key_scheme = "second"

        register_storage(FirstStorage)
        try:
            with self.assertRaises(ValueError):
                register_storage(SecondStorage)
            self.assertIs(STORAGE_BACKENDS["contested"], FirstStorage)
            self.assertIs(register_storage(FirstStorage), FirstStorage)
        finally:
            STORAGE_BACKENDS.pop("contested", None)

        class NamelessStorage(AttachmentStorage):
            key_scheme = "nameless"

        with self.assertRaises(ValueError):
            register_storage(NamelessStorage)
        self.assertNotIn("", STORAGE_BACKENDS)

    def test_stream_key_dispatch(self):
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
        real_execute = self.env.cr.execute

        def fake_execute(query, *args, **kwargs):
            if str(query).startswith("LOCK ir_attachment"):
                raise psycopg.errors.LockNotAvailable("simulated lock timeout")
            return real_execute(query, *args, **kwargs)

        with (
            patch.object(self.env.cr, "commit", lambda: None),
            patch.object(self.env.cr, "rollback", lambda: None),
            patch.object(self.env.cr, "execute", side_effect=fake_execute),
        ):
            result = FileStorage(self.env).autovacuum()
        self.assertIs(result, False)
        with (
            patch.object(self.env.cr, "commit", lambda: None),
            patch.object(self.env.cr, "rollback", lambda: None),
            patch.object(self.env.cr, "execute", side_effect=fake_execute),
        ):
            self.assertIs(self.Attachment._gc_file_store(), False)

    def test_migration_domain_delegation(self):
        cases = (
            ("file", [("db_datas", "!=", False)]),
            ("db", [("store_fname", "!=", False)]),
            ("s3", [("db_datas", "!=", False)]),
        )
        for location, expected in cases:
            with self.subTest(location=location):
                self.icp.set_param("ir_attachment.location", location)
                self.assertEqual(self.Attachment._get_storage_domain(), expected)


class MemoryStorage(AttachmentStorage):
    location = "memory"
    key_scheme = "mem"
    blobs: dict[str, bytes] = {}

    def _key(self, checksum: str) -> str:
        return f"mem://{checksum}"

    def write(self, data, checksum):
        if not data:
            return self._inline_datas_values(data)
        key = self._key(checksum)
        type(self).blobs[key] = bytes(data)
        return {"store_fname": key, "db_datas": False}

    def read(self, key, size=None):
        data = type(self).blobs.get(key, b"")
        return data if size is None else data[:size]

    def delete(self, key):
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
        return [
            "|",
            ("db_datas", "!=", False),
            "&",
            ("store_fname", "!=", False),
            ("store_fname", "not like", "mem://%"),
        ]


@contextlib.contextmanager
def activate_memory_storage(env):
    register_storage(MemoryStorage)
    env["ir.config_parameter"].set_param("ir_attachment.location", "memory")
    try:
        yield MemoryStorage
    finally:
        STORAGE_BACKENDS.pop("memory", None)
        MemoryStorage.blobs.clear()
        env["ir.config_parameter"].set_param("ir_attachment.location", "file")


class TestMemoryStorageCRUD(TransactionCase):
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

            copy = att.copy()
            self.assertEqual(copy.store_fname, att.store_fname)
            copy.invalidate_recordset()
            self.assertEqual(copy.raw, payload)

            att.write({"raw": b"mem-rewritten"})
            att.invalidate_recordset()
            self.assertEqual(att.raw, b"mem-rewritten")
            copy.invalidate_recordset()
            self.assertEqual(copy.raw, payload)

            old_key = copy.store_fname
            copy.unlink()
            self.assertNotIn(old_key, MemoryStorage.blobs)

    def test_streamed_upload_lifecycle(self):
        payload = b"streamed-into-a-custom-backend-" * 40
        text = b"hello indexable streamed content " * 30
        with activate_memory_storage(self.env):
            Attachment = self.env["ir.attachment"]

            att = Attachment._create_from_stream(
                io.BytesIO(payload), name="s.bin", mimetype="application/octet-stream"
            )
            self.assertTrue(att.store_fname.startswith("mem://"))
            self.assertEqual(att.file_size, len(payload))
            self.assertEqual(att.checksum, Attachment._content_checksum(payload))
            att.invalidate_recordset()
            self.assertEqual(att.raw, payload)
            self.assertEqual(att._read_prefix(16), payload[:16])
            self.assertEqual(att._to_http_stream().size, len(payload))

            indexed = Attachment._create_from_stream(
                io.BytesIO(text), name="s.txt", mimetype="text/plain"
            )
            self.assertTrue(
                indexed.index_content,
                "the index read must reach the backend, not the filestore",
            )

            empty = Attachment._create_from_stream(
                io.BytesIO(b""), name="e.bin", mimetype="application/octet-stream"
            )
            self.assertFalse(
                empty.store_fname, "empty content is never keyed externally"
            )
            self.assertEqual(empty.file_size, 0)

    def test_force_storage_migrates_into_memory(self):
        payload = b"fs-to-mem-payload"
        att = self.env["ir.attachment"].create({"name": "fs.bin", "raw": payload})
        self.assertNotIn("://", att.store_fname)
        with activate_memory_storage(self.env):
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
        payload = b"e1-payload"
        with activate_memory_storage(self.env):
            att = self.env["ir.attachment"].create({"name": "e1.bin", "raw": payload})
            MemoryStorage.blobs.clear()
            att.invalidate_recordset()
            self.assertEqual(att.raw, b"")
            copy = att.copy()
            self.assertEqual(copy.file_size, len(payload))
            self.assertEqual(copy.store_fname, att.store_fname)
