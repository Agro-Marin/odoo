"""Regression coverage for ir.actions.report's WeasyPrint URL fetcher.

Audit Tranche 4, finding IAR-T2: the OdooURLFetcher path-traversal guard
(_resolve_static_file) and the _parse_image_url URL parser were entirely
untested. These tests lock the current behaviour of both helpers.
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestReportUrlFetcher(TransactionCase):
    """Lock the OdooURLFetcher static-file guard and image-URL parser."""

    def setUp(self):
        """Build a fetcher instance via the model's public factory."""
        super().setUp()
        self.report = self.env["ir.actions.report"]
        # _build_url_fetcher() returns an OdooURLFetcher; outside an HTTP
        # request _setup_session() is a no-op, so the instance is safe to
        # build and inspect directly in a TransactionCase.
        self.fetcher = self.report._build_url_fetcher()
        self.addCleanup(self.fetcher.cleanup)

    @mute_logger("odoo.addons.base.models.ir_actions_report")
    def test_static_file_rejects_path_traversal(self):
        """A ``../``-escaping static path resolves to nothing (no escape)."""
        # The is_relative_to() guard must reject any candidate that resolves
        # outside the addons root, so a traversal attempt yields None rather
        # than leaking a file from a sibling/parent directory.
        url = "http://localhost/base/static/../../../../../../etc/passwd"
        path = "/base/static/../../../../../../etc/passwd"
        self.assertIsNone(self.fetcher._resolve_static_file(url, path))

    def test_static_file_ignores_non_static_path(self):
        """A path whose 2nd segment is not ``static`` is skipped early."""
        # Guard at the top of _resolve_static_file: parts[1] must be "static".
        self.assertIsNone(
            self.fetcher._resolve_static_file(
                "http://localhost/base/models/foo.py", "/base/models/foo.py"
            )
        )
        # Fewer than 3 segments is also rejected.
        self.assertIsNone(
            self.fetcher._resolve_static_file("http://localhost/base", "/base")
        )

    def test_parse_image_url_variants(self):
        """Table-drive _parse_image_url across its three resolution regexes."""
        cases = [
            # model/id/field, no dimensions -> width/height default to 0
            (
                "/web/image/res.partner/42/image_1920",
                "",
                ("res.partner", 42, "image_1920", 0, 0),
            ),
            # model/id/field with WxH dimensions
            (
                "/web/image/res.partner/42/image_128/64x96",
                "",
                ("res.partner", 42, "image_128", 64, 96),
            ),
            # bare id -> defaults to ir.attachment / raw field
            (
                "/web/image/7",
                "",
                ("ir.attachment", 7, "raw", 0, 0),
            ),
            # bare id with a unique suffix and dimensions
            (
                "/web/image/7-deadbeef/20x30",
                "",
                ("ir.attachment", 7, "raw", 20, 30),
            ),
            # query-string fallback when the path matches no regex
            (
                "/web/image",
                "model=res.users&id=3&field=avatar_128&width=10&height=15",
                ("res.users", 3, "avatar_128", 10, 15),
            ),
            # query-string fallback with only an id -> model/field defaults
            (
                "/web/image",
                "id=9",
                ("ir.attachment", 9, "raw", 0, 0),
            ),
        ]
        for path, query, expected in cases:
            with self.subTest(path=path, query=query):
                self.assertEqual(self.fetcher._parse_image_url(path, query), expected)

    def test_parse_image_url_missing_id_raises(self):
        """The query-string fallback raises ValueError when no id is given."""
        # No regex matches the path and the query lacks an id, so res_id is 0
        # and the guard raises ValueError.
        with self.assertRaises(ValueError):
            self.fetcher._parse_image_url("/web/image", "model=res.partner")
