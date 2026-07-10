import base64
from types import SimpleNamespace
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import Stream
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.misc import limited_field_access_token

from odoo.addons.base.tests.common import TransactionCaseWithUserDemo

# 1x1 px PNG, base64-encoded (same fixture used by test_image.py).
PNG_1x1_B64 = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"


@tagged("post_install", "-at_install")
class TestIrBinaryNoRequest(TransactionCase):
    """IRB-L1: _get_image_stream_from must not dereference the thread-local
    `request` proxy on the no-request path (cron/worker resolving /web/image
    server-side); previously it raised AttributeError, downgrading the
    deadlock-avoidance fast path to an HTTP self-fetch.

    Stream resolution is mocked to a ready data stream to isolate the
    request-handling branch from the attachment-streaming path.
    """

    def test_get_image_stream_from_without_request(self):
        raw_png = base64.b64decode(PNG_1x1_B64)
        data_stream = Stream(
            type="data",
            data=raw_png,
            mimetype="image/png",
            etag="audit-irb-l1",
            size=len(raw_png),
        )
        ir_binary = self.env["ir.binary"]
        partner = self.env["res.partner"].create({"name": "Audit IRB-L1"})

        with (
            patch("odoo.addons.base.models.ir_binary.request", None),
            patch.object(type(ir_binary), "_get_stream_from", return_value=data_stream),
        ):
            stream = ir_binary._get_image_stream_from(
                partner, "image_1920", width=64, height=64
            )

        # With no request the image is (re)processed and returned as a data
        # stream instead of raising on request.httprequest.environ.
        self.assertEqual(stream.type, "data")
        self.assertTrue(stream.data)


@tagged("post_install", "-at_install")
class TestIrAttachmentNoRequest(TransactionCase):
    """NEW-1 (found while testing IRB-L1): a filestore attachment's
    _to_http_stream must resolve the filestore path without an HTTP request
    (cron / server-side rendering), where `request` is unbound; previously it
    raised on request.db.
    """

    def test_to_http_stream_without_request(self):
        att = self.env["ir.attachment"].create({"name": "audit-new1", "raw": b"hello"})
        self.assertTrue(att.store_fname, "expected a filestore-backed attachment")
        with patch("odoo.addons.base.models.ir_attachment.request", None):
            stream = att._to_http_stream()
        self.assertEqual(stream.type, "path")
        self.assertEqual(stream.size, 5)


@tagged("post_install", "-at_install")
class TestIrBinaryImageMissing(TransactionCase):
    """IRB-C1: _get_image_stream_from must degrade to the placeholder when
    _get_stream_from raises MissingError (e.g. a dangling attachment-backed
    binary field) instead of escaping to a 500; previously only UserError was
    caught.
    """

    def test_missing_error_falls_back_to_placeholder(self):
        ir_binary = self.env["ir.binary"]
        partner = self.env["res.partner"].create({"name": "Audit IRB-C1"})

        def raise_missing(*args, **kwargs):
            raise MissingError("The related attachment does not exist.")

        with (
            patch("odoo.addons.base.models.ir_binary.request", None),
            patch.object(
                type(ir_binary), "_get_stream_from", side_effect=raise_missing
            ),
        ):
            stream = ir_binary._get_image_stream_from(partner, "image_1920")

        # A placeholder stream is returned rather than the MissingError escaping.
        # The placeholder image is read into memory, so the stream is type "data".
        self.assertIsNotNone(stream)
        self.assertEqual(stream.type, "data")


@tagged("post_install", "-at_install")
class TestIrBinaryFindRecordAccess(TransactionCaseWithUserDemo):
    """IRB-T1: exercise the access-control branches of _find_record -- a valid
    field-scoped token grants sudo, a mismatched token does not, and an
    unreadable record falls through to check_access and raises.
    """

    def test_valid_field_token_grants_sudo(self):
        partner = self.env["res.partner"].create({"name": "Audit IRB-T1 token"})
        token = limited_field_access_token(partner, "image_1920", scope="binary")
        record = (
            self.env["ir.binary"]
            .with_user(self.user_demo)
            ._find_record(
                res_model="res.partner",
                res_id=partner.id,
                access_token=token,
                field="image_1920",
            )
        )
        self.assertTrue(record.env.su, "a valid field token must return a sudo record")

    def test_mismatched_token_does_not_grant_sudo(self):
        partner = self.env["res.partner"].create({"name": "Audit IRB-T1 bad token"})
        # res.partner is readable by an internal user, so the fall-through
        # check_access succeeds and returns a NON-sudo record.
        record = (
            self.env["ir.binary"]
            .with_user(self.user_demo)
            ._find_record(
                res_model="res.partner",
                res_id=partner.id,
                access_token="not-a-valid-tokeno0",
                field="image_1920",
            )
        )
        self.assertFalse(
            record.env.su, "a mismatched token must not bypass to a sudo record"
        )

    def test_no_read_access_falls_through_and_raises(self):
        # ir.exports is gated on base.group_allow_export (IEXP-L1); demo is a
        # plain internal user, so check_access("read") must raise on the
        # _find_record fall-through path.
        export_group = self.env.ref("base.group_allow_export")
        self.user_demo.write({"group_ids": [Command.unlink(export_group.id)]})
        preset = self.env["ir.exports"].create({"name": "preset", "resource": "x"})
        with self.assertRaises(AccessError):
            self.env["ir.binary"].with_user(self.user_demo)._find_record(
                res_model="ir.exports", res_id=preset.id
            )


@tagged("post_install", "-at_install")
class TestIrBinaryImageBranches(TransactionCase):
    """IRB-C2 + branch coverage for _get_image_stream_from.

    Pins the previously untested branches: the swallowed-exception DEBUG trace,
    the explicit-download re-raise, the ETag augmentation on post-processing,
    and the empty-stream placeholder fallback.
    """

    @property
    def _binary(self):
        return self.env["ir.binary"]

    def _partner(self, name):
        return self.env["res.partner"].create({"name": name})

    def _png_stream(self, etag="audit-irb-c2"):
        raw_png = base64.b64decode(PNG_1x1_B64)
        return Stream(
            type="data",
            data=raw_png,
            mimetype="image/png",
            etag=etag,
            size=len(raw_png),
        )

    def test_swallowed_error_is_logged_at_debug(self):
        """The placeholder fallback must leave a DEBUG trace naming the
        swallowed exception, or genuine programming errors (typo'd
        field_name) are undiagnosable."""
        partner = self._partner("Audit IRB-C2 log")

        def raise_user_error(*args, **kwargs):
            raise UserError("Record has no field 'image_1920_typo'.")

        with (
            patch("odoo.addons.base.models.ir_binary.request", None),
            patch.object(
                type(self._binary), "_get_stream_from", side_effect=raise_user_error
            ),
            self.assertLogs("odoo.addons.base.models.ir_binary", level="DEBUG") as cm,
        ):
            stream = self._binary._get_image_stream_from(partner, "image_1920")
        self.assertEqual(stream.type, "data")  # the placeholder still serves
        joined = "\n".join(cm.output)
        self.assertIn("image placeholder", joined)
        self.assertIn("image_1920_typo", joined)
        self.assertIn("res.partner", joined)

    def test_explicit_download_re_raises(self):
        """?download requests must surface the error, not a placeholder."""
        partner = self._partner("Audit IRB-C2 download")
        fake_request = SimpleNamespace(params={"download": "1"})

        def raise_missing(*args, **kwargs):
            raise MissingError("The related attachment does not exist.")

        with (
            patch("odoo.addons.base.models.ir_binary.request", fake_request),
            patch.object(
                type(self._binary), "_get_stream_from", side_effect=raise_missing
            ),
        ):
            with self.assertRaises(MissingError):
                self._binary._get_image_stream_from(partner, "image_1920")

    def test_empty_stream_falls_back_to_placeholder(self):
        """A zero-size stream degrades to the placeholder like an error."""
        partner = self._partner("Audit IRB-C2 empty")
        empty = Stream(type="data", data=b"", mimetype="image/png", size=0)
        with (
            patch("odoo.addons.base.models.ir_binary.request", None),
            patch.object(type(self._binary), "_get_stream_from", return_value=empty),
        ):
            stream = self._binary._get_image_stream_from(partner, "image_1920")
        self.assertEqual(stream.type, "data")
        self.assertTrue(stream.size, "placeholder must carry actual bytes")

    def test_etag_augmented_with_processing_params(self):
        """Post-processing parameters must be baked into the ETag, or a
        resized variant would be served from the cache of another size."""
        partner = self._partner("Audit IRB-C2 etag")
        with (
            patch("odoo.addons.base.models.ir_binary.request", None),
            patch.object(
                type(self._binary),
                "_get_stream_from",
                return_value=self._png_stream(etag="base-etag"),
            ),
        ):
            stream = self._binary._get_image_stream_from(
                partner, "image_1920", width=64, height=32, crop=True, quality=80
            )
        self.assertEqual(stream.etag, "base-etag-64x32-crop=True-quality=80")
        self.assertEqual(stream.type, "data")
        self.assertTrue(stream.data)
