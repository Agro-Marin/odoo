"""Regression tests for the 2026-06-10 ir_attachment review fixes.

Each test locks in one fixed behavior:

- copy() relinks filestore content without reading bytes (B4) and no longer
  produces silently-empty copies when the file is unreadable (A1)
- write() content precedence matches create(): raw wins over datas (A3),
  the base64 payload is decoded exactly once (B2), str raw is encoded (A4)
- force_storage() tolerates custom storage locations (A5)
- _to_http_stream() degrades gracefully on corrupted store_fname (A2)
- create_unique() batch-creates misses and dedups via explicit context (B3/C4)
- _migrate_remote_to_local() reports instead of raising for url type (C2)
- regenerate_assets_bundles() is explicitly admin-gated (C6)
- image autoresize tolerates whitespace in the extension list param (D2)
- create() passes a caller-supplied db_datas through untouched (R1) and
  applies write()'s key-presence content precedence (A3 alignment)
- condition_values() never returns a lazy Query value (R2)
- an unowned store-key scheme degrades to an empty read, not a crash (R3)
- _search's per-model and batched-fallback branches return the same rows
  across the _SEARCH_MODEL_DOMAIN_LIMIT boundary (R4)
- _from_request_file GUESS mode survives an empty upload (R5)
"""

import base64
import hashlib
import inspect
import io
import os
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from odoo.exceptions import AccessError
from odoo.fields import Domain
from odoo.tools import Query, mute_logger

from odoo.addons.base.models.ir_attachment import IrAttachment, condition_values
from odoo.addons.base.models.ir_autovacuum import is_autovacuum
from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


def _big_jpeg() -> bytes:
    """Return a noisy 3000x2000 JPEG larger than the 1920px default limit."""
    buf = io.BytesIO()
    img = Image.new("RGB", (3000, 2000))
    img.putdata(
        [((x * 7) % 256, (x * 13) % 256, (x * 29) % 256) for x in range(3000 * 2000)]
    )
    img.save(buf, "JPEG")
    return buf.getvalue()


class TestIrAttachmentReviewFixes(TransactionCaseWithUserDemo):
    def setUp(self):
        super().setUp()
        self.Attachment = self.env["ir.attachment"]

    def test_copy_filestore_relinks_without_reading(self):
        """copy() must not read the bytes; it relinks the existing file."""
        payload = b"b4-" + os.urandom(1024)
        att = self.Attachment.create(
            {"name": "b4.bin", "raw": payload, "mimetype": "application/octet-stream"}
        )
        att.invalidate_recordset()

        reads = []
        orig = IrAttachment._file_read

        def spy(model, fname, size=None):
            reads.append(fname)
            return orig(model, fname, size)

        with patch.object(IrAttachment, "_file_read", spy):
            copy = att.copy()

        self.assertFalse(reads, "copy() should not read filestore content")
        self.assertEqual(copy.store_fname, att.store_fname)
        self.assertEqual(copy.checksum, att.checksum)
        self.assertEqual(copy.file_size, att.file_size)
        self.assertEqual(copy.db_datas, att.db_datas)
        copy.invalidate_recordset()
        self.assertEqual(copy.raw, payload)

        # explicit content override still takes the content path
        override = att.copy({"raw": b"other content"})
        self.assertEqual(override.raw, b"other content")
        self.assertNotEqual(override.checksum, att.checksum)

    def test_copy_preserves_metadata_on_missing_file(self):
        """A transient/missing file no longer yields a silently empty copy."""
        payload = b"a1-payload-" + os.urandom(64)
        att = self.Attachment.create(
            {"name": "a1.bin", "raw": payload, "mimetype": "application/octet-stream"}
        )
        Path(att._full_path(att.store_fname)).unlink()
        att.invalidate_recordset()

        copy = att.copy()

        self.assertEqual(copy.file_size, len(payload))
        self.assertEqual(copy.checksum, att.checksum)
        self.assertEqual(copy.store_fname, att.store_fname)

    def test_copy_db_storage_content(self):
        """db-stored attachments still copy content through `raw`."""
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        payload = b"db-payload"
        att = self.Attachment.create({"name": "db.bin", "raw": payload})
        self.assertFalse(att.store_fname)
        copy = att.copy()
        self.assertEqual(copy.raw, payload)
        self.assertEqual(copy.checksum, att.checksum)
        self.assertEqual(copy.file_size, len(payload))

    def test_write_raw_and_datas_raw_wins(self):
        """write() content precedence matches create(): raw wins over datas."""
        raw_content = b"RAWWINS"
        datas_content = base64.b64encode(b"DATASWINS")

        att1 = self.Attachment.create({"name": "a3-1.txt", "raw": b"orig"})
        att1.write({"raw": raw_content, "datas": datas_content})
        att1.invalidate_recordset()
        self.assertEqual(att1.raw, raw_content)

        att2 = self.Attachment.create({"name": "a3-2.txt", "raw": b"orig"})
        att2.write({"datas": datas_content, "raw": raw_content})
        att2.invalidate_recordset()
        self.assertEqual(att2.raw, raw_content)

        # datas alone still writes content
        att2.write({"datas": datas_content})
        att2.invalidate_recordset()
        self.assertEqual(att2.raw, b"DATASWINS")

    def test_write_datas_single_decode(self):
        """write({'datas': ...}) decodes the base64 payload exactly once."""
        att = self.Attachment.create({"name": "b2.txt", "raw": b"orig"})
        payload_b64 = base64.b64encode(b"plain text payload")

        decodes = []
        orig = base64.b64decode

        def spy(*args, **kwargs):
            decodes.append(args)
            return orig(*args, **kwargs)

        with patch.object(base64, "b64decode", spy):
            att.write({"datas": payload_b64})
            self.env.flush_all()

        self.assertEqual(len(decodes), 1, "expected exactly one base64 decode")
        att.invalidate_recordset()
        self.assertEqual(att.raw, b"plain text payload")

    def test_write_str_raw(self):
        """str content in write({'raw': ...}) is encoded like in create()."""
        att = self.Attachment.create({"name": "a4.txt", "raw": b"x"})
        att.write({"raw": "string content"})
        att.invalidate_recordset()
        self.assertEqual(att.raw, b"string content")

    def test_force_storage_custom_location(self):
        """Unknown ir_attachment.location values behave like 'file'."""
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "s3")
        # must not raise (previously KeyError in _get_storage_domain)
        self.Attachment.force_storage()
        self.assertEqual(
            self.Attachment._get_storage_domain(), [("db_datas", "!=", False)]
        )

    def test_to_http_stream_unsafe_store_fname(self):
        """A corrupted store_fname degrades to an empty stream, not a crash."""
        att = self.Attachment.create({"name": "a2.bin", "raw": b"a2-payload"})
        self.env.cr.execute(
            "UPDATE ir_attachment SET store_fname = %s WHERE id = %s",
            ["../evil", att.id],
        )
        att.invalidate_recordset()
        stream = att._to_http_stream()
        self.assertEqual(stream.type, "data")
        self.assertEqual(stream.data, b"")
        self.assertEqual(stream.size, 0)

    def test_create_unique_batches_creates(self):
        """create_unique() creates all misses in one batch and dedups."""
        count = [0]
        orig = IrAttachment.create

        def spy(model, vals_list):
            count[0] += 1
            return orig(model, vals_list)

        # mimetype matters: the dedup key is (checksum, file_size, mimetype)
        # and _check_contents re-guesses 'application/octet-stream' from the
        # content, so declare the type these text payloads will actually get
        def vals(payload):
            return {
                "name": "cu.txt",
                "datas": base64.b64encode(payload),
                "mimetype": "text/plain",
            }

        values = [vals(b"cu-1"), vals(b"cu-2"), vals(b"cu-3"), vals(b"cu-1")]
        with patch.object(IrAttachment, "create", spy):
            ids = self.Attachment.create_unique(values)

        self.assertEqual(count[0], 1, "misses must be created in a single batch")
        self.assertEqual(len(ids), 4)
        self.assertEqual(ids[0], ids[3], "in-batch duplicate must dedup")
        self.assertEqual(len(set(ids[:3])), 3)

        # second call: everything dedups, no create at all
        count[0] = 0
        with patch.object(IrAttachment, "create", spy):
            ids2 = self.Attachment.create_unique(values)
        self.assertEqual(count[0], 0)
        self.assertEqual(ids2, ids)

    def test_create_unique_matches_res_field_attachments(self):
        """The dedup search must see attachments hidden behind res_field."""
        partner = self.env["res.partner"].create({"name": "CU Partner"})
        field_att = self.Attachment.create(
            {
                "name": "field.txt",
                "raw": b"cu-field-payload",
                "mimetype": "text/plain",
                "res_model": "res.partner",
                "res_id": partner.id,
                "res_field": "image_1920",
            }
        )
        ids = self.Attachment.create_unique(
            [
                {
                    "name": "same.txt",
                    "datas": base64.b64encode(b"cu-field-payload"),
                    "mimetype": "text/plain",
                }
            ]
        )
        self.assertEqual(ids, [field_att.id])

    def test_migrate_remote_to_local_contract(self):
        """url attachments report False instead of raising; binary True."""
        url_att = self.Attachment.create(
            {"name": "remote", "type": "url", "url": "https://example.com/x.png"}
        )
        self.assertFalse(url_att._migrate_remote_to_local())
        bin_att = self.Attachment.create({"name": "local.bin", "raw": b"x"})
        self.assertTrue(bin_att._migrate_remote_to_local())

    def test_regenerate_assets_bundles_requires_admin(self):
        """Non-admin users are rejected explicitly, before any unlink."""
        with self.assertRaises(AccessError):
            self.Attachment.with_user(self.user_demo).regenerate_assets_bundles()

    def test_search_fallback_keyset_pagination(self):
        """Multi-batch fallback search returns the same ids as single-batch.

        Patches PREFETCH_MAX small so the keyset (and OFFSET-fallback)
        batching crosses several batch boundaries, including batches fully
        consumed by inaccessible records.
        """
        partners = self.env["res.partner"].create([{"name": f"K{i}"} for i in range(3)])
        cron = self.env["ir.cron"].sudo().search([], limit=1)
        vals_list = [
            {
                "name": f"k-linked-{i}.txt",
                "raw": b"k-%d" % i,
                "res_model": "res.partner",
                "res_id": partners[i % 3].id,
            }
            for i in range(12)
        ]
        vals_list.extend(
            {"name": f"k-public-{i}.txt", "raw": b"kp-%d" % i, "public": True}
            for i in range(3)
        )
        if cron:
            # inaccessible to demo: linked to a model demo cannot read
            vals_list.extend(
                {
                    "name": f"k-cron-{i}.txt",
                    "raw": b"kc-%d" % i,
                    "res_model": "ir.cron",
                    "res_id": cron.id,
                }
                for i in range(4)
            )
        self.Attachment.create(vals_list)
        # owned by demo, no linked record
        self.Attachment.with_user(self.user_demo).create(
            {"name": "k-own.txt", "raw": b"k-own"}
        )

        Demo = self.Attachment.with_user(self.user_demo)
        baseline_unbounded = Demo.search([]).ids
        baseline_limited = Demo.search([], limit=6).ids
        baseline_paged = Demo.search([], offset=4, limit=6).ids
        baseline_ordered = Demo.search([], order="name desc, id").ids

        with patch("odoo.addons.base.models.ir_attachment.PREFETCH_MAX", 5):
            self.assertEqual(Demo.search([]).ids, baseline_unbounded)
            self.assertEqual(Demo.search([], limit=6).ids, baseline_limited)
            self.assertEqual(Demo.search([], offset=4, limit=6).ids, baseline_paged)
            self.assertEqual(
                Demo.search([], order="name desc, id").ids, baseline_ordered
            )

    def test_get_image_autoresize_config_guards(self):
        """Misconfigured autoresize params degrade, never crash."""
        icp = self.env["ir.config_parameter"]
        Attachment = self.Attachment

        icp.set_param("base.image_autoresize_extensions", "png, jpeg")
        subtypes, _w, _h, _q = Attachment._get_image_autoresize_config()
        self.assertIn("jpeg", subtypes)

        icp.set_param("base.image_autoresize_max_px", "0")
        self.assertEqual(Attachment._get_image_autoresize_config()[1], 0)

        icp.set_param("base.image_autoresize_max_px", "axb")
        self.assertEqual(Attachment._get_image_autoresize_config()[1], 0)

        icp.set_param("base.image_autoresize_max_px", "800x600")
        icp.set_param("base.image_autoresize_quality", "not-a-number")
        subtypes, max_w, max_h, quality = Attachment._get_image_autoresize_config()
        self.assertEqual((max_w, max_h, quality), (800, 600, 80))

    def test_mixed_storage_state_reads_follow_record(self):
        """Reads/streams follow the record's store key, not the location param.

        ``ir_attachment.location`` only governs where NEW content goes;
        switching it does not migrate existing rows (force_storage is
        optional). This invariant is load-bearing for the storage-backend
        plan (C1): read/stream/delete dispatch must stay record-driven.
        """
        icp = self.env["ir.config_parameter"]

        # file-stored row, then switch the location to db
        file_att = self.Attachment.create(
            {"name": "mix-file.bin", "raw": b"file-payload"}
        )
        self.assertTrue(file_att.store_fname)
        icp.set_param("ir_attachment.location", "db")

        file_att.invalidate_recordset()
        self.assertEqual(file_att.raw, b"file-payload")
        stream = file_att._to_http_stream()
        self.assertEqual(stream.type, "path")

        # new content goes to the configured backend (db)...
        db_att = self.Attachment.create({"name": "mix-db.bin", "raw": b"db-payload"})
        self.assertFalse(db_att.store_fname)
        self.assertEqual(db_att.db_datas, b"db-payload")

        # ...while the old file row still reads from disk; and switching
        # back leaves the db row readable too (both directions hold)
        icp.set_param("ir_attachment.location", "file")
        db_att.invalidate_recordset()
        self.assertEqual(db_att.raw, b"db-payload")

    def test_gc_sweeps_file_checklist_under_db_location(self):
        """The file checklist is swept even when location='db'.

        C1 Phase 4 improvement: the autovacuum hook iterates ALL registered
        backends, so a switched-away backend still collects its keys.
        Previously the single-backend gate left marked files orphaned
        forever while ``location='db'``.
        """
        file_att = self.Attachment.create(
            {"name": "gc-mix.bin", "raw": b"gc-sweep-" + os.urandom(16)}
        )
        full_path = Path(file_att._full_path(file_att.store_fname))
        self.assertTrue(full_path.is_file())
        file_att.unlink()  # marks the file for GC
        self.env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        # cr.commit() is forbidden inside tests — stub it; the LOCK and the
        # sweep run in the test transaction, and the filesystem unlink
        # (which is what we assert) is not transactional anyway
        with patch.object(self.env.cr, "commit", lambda: None):
            self.assertIsNone(self.Attachment._gc_file_store())
        self.assertFalse(
            full_path.is_file(),
            "file checklist must be swept even under db location",
        )

    def test_autoresize_extensions_tolerate_whitespace(self):
        """Whitespace in the extension list must not disable the resize."""
        img = _big_jpeg()
        self.env["ir.config_parameter"].set_param(
            "base.image_autoresize_extensions", "png, jpeg"
        )
        att = self.Attachment.create({"name": "d2.jpg", "raw": img})
        self.assertLess(att.file_size, len(img), "image was not resized")

    def test_create_db_datas_passthrough(self):
        """create() with only db_datas keeps the payload, computes nothing (R1).

        Vanilla contract pinned by test_http's test_static17/18: a raw-column
        create is the missing-checksum serving path. Defaulting raw to b""
        used to overwrite the payload with empty bytes and stamp sha1(b"").
        """
        payload = b"db-direct-payload"
        att = self.Attachment.create({"name": "direct.txt", "db_datas": payload})
        self.assertEqual(att.raw, payload, "payload must survive create")
        self.assertFalse(att.checksum, "no content key -> no computed metadata")
        self.assertFalse(att.file_size)
        self.assertFalse(att.store_fname)

        # a db_datas copy default must keep the override, not blank it
        copy = att.copy({"db_datas": b"copied-payload"})
        self.assertEqual(copy.raw, b"copied-payload")
        self.assertFalse(copy.checksum)

    def test_create_content_key_presence_precedence(self):
        """create() matches write(): an explicit empty raw beats datas (A3).

        Precedence is by key presence, not truthiness — and an explicitly
        empty content key still gets the IRA-P0-7 empty-content checksum.
        """
        empty_sha = hashlib.sha1(b"", usedforsecurity=False).hexdigest()
        att = self.Attachment.create(
            {"name": "p.txt", "raw": b"", "datas": base64.b64encode(b"LOSER")}
        )
        self.assertFalse(att.raw, "explicit empty raw must win over datas")
        self.assertEqual(att.checksum, empty_sha, "explicit empty is checksummed")

        # a falsy datas key alone is still explicit (empty) content
        att2 = self.Attachment.create({"name": "p2.txt", "datas": False})
        self.assertFalse(att2.raw)
        self.assertEqual(att2.checksum, empty_sha)

    def test_condition_values_contract(self):
        """condition_values returns materialized values or None — never a
        lazy Query (R2): callers probe the result with ``in`` / ``len()``,
        which on a Query executes and scans the subquery.
        """
        Att = self.Attachment
        self.assertEqual(
            list(condition_values(Att, "res_id", Domain("res_id", "=", 7))), [7]
        )
        in_values = condition_values(Att, "res_id", Domain("res_id", "in", [1, 2]))
        self.assertEqual(set(in_values), {1, 2})
        # field not restricted at all
        self.assertIsNone(condition_values(Att, "res_id", Domain("public", "=", True)))
        # an OR branch does not restrict the field either
        or_domain = Domain("res_id", "=", 1) | Domain("public", "=", True)
        self.assertIsNone(condition_values(Att, "res_id", or_domain))
        # the lazy-value guard itself
        query = self.env["res.partner"]._search([])
        result = condition_values(Att, "res_id", Domain("res_id", "in", query))
        self.assertNotIsInstance(result, Query)

    def test_search_with_query_valued_res_id(self):
        """A Query-valued res_id condition flows through the non-su _search."""
        partner = self.env["res.partner"].create({"name": "Query Valued"})
        att = self.Attachment.create(
            {
                "name": "qv.txt",
                "raw": b"qv",
                "res_model": "res.partner",
                "res_id": partner.id,
            }
        )
        query = self.env["res.partner"]._search([("id", "=", partner.id)])
        found = self.Attachment.with_user(self.user_demo).search(
            [("res_model", "=", "res.partner"), ("res_id", "in", query)]
        )
        self.assertIn(att.id, found.ids)

    def test_search_model_domain_limit_fallback_equivalence(self):
        """Above _SEARCH_MODEL_DOMAIN_LIMIT, the batched fallback branch of
        _search returns the same accessible rows as the per-model branch.
        """
        partner = self.env["res.partner"].create({"name": "Limit Probe"})
        country = self.env.ref("base.mx")
        a1 = self.Attachment.create(
            {
                "name": "lim-p.txt",
                "raw": b"1",
                "res_model": "res.partner",
                "res_id": partner.id,
            }
        )
        a2 = self.Attachment.create(
            {
                "name": "lim-c.txt",
                "raw": b"2",
                "res_model": "res.country",
                "res_id": country.id,
            }
        )
        domain = [
            ("id", "in", (a1 | a2).ids),
            ("res_model", "in", ["res.partner", "res.country"]),
        ]
        Demo = self.Attachment.with_user(self.user_demo)
        baseline = Demo.search(domain).ids  # 2 models <= limit: per-model branch
        with patch.object(IrAttachment, "_SEARCH_MODEL_DOMAIN_LIMIT", 1):
            fallback = Demo.search(domain).ids
        self.assertEqual(set(baseline), {a1.id, a2.id})
        self.assertEqual(set(fallback), set(baseline), "branches must agree")

    def test_from_request_file_guess_empty(self):
        """GUESS mode on an empty upload must survive the rewind seek."""

        class _EmptyFile:
            content_type = "application/octet-stream"
            filename = "empty.bin"

            def __init__(self):
                self._buf = io.BytesIO(b"")

            def read(self, size=-1):
                return self._buf.read(size)

            def seek(self, offset, whence=0):
                return self._buf.seek(offset, whence)

        att = self.Attachment._from_request_file(_EmptyFile(), mimetype="GUESS")
        self.assertTrue(att.id)
        self.assertFalse(att.raw)

    @mute_logger("odoo.addons.base.models.ir_attachment")
    def test_backend_for_key_unknown_scheme_degrades(self):
        """A store key with an unowned URI scheme reads as empty, no crash (R3).

        backend_for_key falls back to FileStorage for unknown schemes (e.g. a
        custom backend module was uninstalled); the sanitized path misses and
        _file_read degrades to b"".
        """
        att = self.Attachment.create({"name": "s3.bin", "raw": b"s3-payload"})
        self.env.cr.execute(
            "UPDATE ir_attachment SET store_fname = %s WHERE id = %s",
            ["s3://bucket/key", att.id],
        )
        att.invalidate_recordset()
        self.assertEqual(att.raw, b"")

    def test_is_xml_like_mimetype_is_precise(self):
        """The serve-time markup gate matches on subtype, not a substring.

        Pins the fix for the ``"ht" in mimetype`` over-match: every genuinely
        script-bearing markup type is caught, and no type whose NAME merely
        contains "ht"/"xml" (e.g. ``text/richtext``, ``rights-management``,
        ``belightsoft.lhzd+zip``, ``silverlight``, the Office OpenXML zip
        containers) is misclassified.
        """
        Att = self.Attachment
        for mt in (
            "text/html",
            "application/xhtml+xml",
            "image/svg+xml",
            "text/xml",
            "application/xml",
            "application/hta",
            "application/rss+xml",
            "application/mathml+xml",
        ):
            self.assertTrue(Att._is_xml_like_mimetype(mt), f"{mt} must be neutralized")
        for mt in (
            "text/richtext",
            "application/vnd.ibm.rights-management",
            "application/vnd.belightsoft.lhzd+zip",
            "application/x-silverlight",
            "application/x-httpd-php",
            "audio/x-aac",
            "image/png",
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ):
            self.assertFalse(Att._is_xml_like_mimetype(mt), f"{mt} must be preserved")

    def test_check_contents_neutralizes_only_real_markup(self):
        """For an untrusted uploader, markup is forced to text/plain but a
        coincidentally "ht"/"xml"-named binary keeps its mimetype.
        """
        demo = self.Attachment.with_user(self.user_demo)
        # demo cannot author views, so the neutralization branch is active
        self.assertFalse(
            self.env["ir.ui.view"].with_user(self.user_demo).has_access("write")
        )
        for mt in ("text/html", "image/svg+xml", "application/xml"):
            out = demo._check_contents({"mimetype": mt, "raw": b"<x/>"})
            self.assertEqual(out["mimetype"], "text/plain", mt)
        # the previously misclassified types must now survive untouched
        for mt in (
            "text/richtext",
            "application/vnd.belightsoft.lhzd+zip",
            "application/vnd.ibm.rights-management",
        ):
            out = demo._check_contents({"mimetype": mt, "raw": b"PK\x03\x04data"})
            self.assertEqual(out["mimetype"], mt, mt)

    def test_unreadable_filestore_content_is_observable(self):
        """A missing/unreadable referenced file is logged (not silently empty).

        A store key is only ever set for non-empty content, so an empty read
        signals a filestore fault; ``_compute_raw`` must surface it at ERROR
        with the record identity while still degrading to b"" for the reader.
        """
        payload = b"a2-observable-" + os.urandom(48)
        att = self.Attachment.create(
            {"name": "a2.bin", "raw": payload, "mimetype": "application/octet-stream"}
        )
        self.assertTrue(att.store_fname)
        Path(att._full_path(att.store_fname)).unlink()
        att.invalidate_recordset()

        with self.assertLogs(
            "odoo.addons.base.models.ir_attachment", level="ERROR"
        ) as captured:
            self.assertEqual(att.raw, b"", "reader still degrades to empty bytes")
        self.assertTrue(
            any(
                "Unreadable filestore content" in line and str(att.id) in line
                for line in captured.output
            ),
            f"expected an ERROR naming attachment {att.id}, got {captured.output}",
        )
        # metadata is untouched: the row still describes its (now missing) content
        self.assertEqual(att.file_size, len(payload))

    def test_esm_lifecycle_methods_survive_module_split(self):
        """The ESM/asset lifecycle moved to ir_attachment_assets.py via a
        same-module ``_inherit`` extension. It must remain part of the
        ir.attachment model — methods resolvable and, crucially, the
        ``@api.autovacuum`` registration of ``_gc_esm_assets`` preserved
        (autovacuum is collected by walking the composed model MRO).
        """
        Att = self.Attachment
        self.assertTrue(callable(Att._esm_asset_domain))
        self.assertTrue(callable(Att._gc_esm_assets))
        self.assertTrue(callable(Att.regenerate_assets_bundles))
        self.assertEqual(Att._ESM_GC_GRACE_DAYS, 7)
        # _esm_asset_domain still produces the /web/assets/ identity domain
        self.assertIn(("url", "=like", "/web/assets/%"), list(Att._esm_asset_domain()))

        autovacuums = {
            name for name, _f in inspect.getmembers(type(Att), is_autovacuum)
        }
        # moved into the extension file...
        self.assertIn("_gc_esm_assets", autovacuums)
        # ...while these stayed in the core file and must also still register
        self.assertIn("_audit_url_attachments", autovacuums)
        self.assertIn("_gc_file_store", autovacuums)
