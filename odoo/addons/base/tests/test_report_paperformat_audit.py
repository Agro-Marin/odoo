"""Audit tests for report.paperformat (RPF-T1).

Cover print page size for named formats (both orientations) and custom formats,
plus the _check_format_or_page constraint forbidding a named format with explicit
page dimensions.
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.base.models.report_paperformat import (
    PAPER_SIZE_BY_KEY,
    PAPER_SIZES,
)

# A4 in mm, as stored in PAPER_SIZES (width x height, portrait orientation).
A4_WIDTH = 210.0
A4_HEIGHT = 297.0


@tagged("post_install", "-at_install")
class TestReportPaperformatAudit(TransactionCase):
    """Computed print page size and format/page mutual-exclusion constraint."""

    def test_a4_portrait_dimensions(self):
        """RPF-T1: A4 portrait yields 210 x 297 mm."""
        pf = self.env["report.paperformat"].create(
            {"name": "audit A4 portrait", "format": "A4", "orientation": "Portrait"}
        )
        self.assertAlmostEqual(pf.print_page_width, A4_WIDTH)
        self.assertAlmostEqual(pf.print_page_height, A4_HEIGHT)

    def test_a4_landscape_dimensions_swapped(self):
        """RPF-T1: A4 landscape swaps width and height."""
        pf = self.env["report.paperformat"].create(
            {"name": "audit A4 landscape", "format": "A4", "orientation": "Landscape"}
        )
        self.assertAlmostEqual(pf.print_page_width, A4_HEIGHT)
        self.assertAlmostEqual(pf.print_page_height, A4_WIDTH)

    def test_custom_format_honors_explicit_dimensions(self):
        """RPF-T1: custom format reports the explicit page width/height."""
        pf = self.env["report.paperformat"].create(
            {
                "name": "audit custom",
                "format": "custom",
                "orientation": "Portrait",
                "page_width": 150,
                "page_height": 250,
            }
        )
        self.assertAlmostEqual(pf.print_page_width, 150)
        self.assertAlmostEqual(pf.print_page_height, 250)

    def test_named_format_with_page_dimensions_rejected(self):
        """RPF-T1: _check_format_or_page forbids a named format with explicit dims."""
        with self.assertRaises(ValidationError):
            self.env["report.paperformat"].create(
                {
                    "name": "audit A4 with width",
                    "format": "A4",
                    "page_width": 100,
                }
            )

    def test_default_field_dropped(self):
        """The write-only `default` field was dropped: company defaults resolve
        via res.company.paperformat_id, and nothing ever read the flag."""
        self.assertNotIn("default", self.env["report.paperformat"]._fields)

    def test_paper_size_key_map_matches_list(self):
        """PAPER_SIZE_BY_KEY is the shared O(1) companion of PAPER_SIZES."""
        self.assertEqual(len(PAPER_SIZE_BY_KEY), len(PAPER_SIZES))
        for paper_size in PAPER_SIZES:
            self.assertIs(PAPER_SIZE_BY_KEY[paper_size["key"]], paper_size)

    def test_non_a4_named_format_dimensions(self):
        """A named format resolved through the key map yields its mm size."""
        pf = self.env["report.paperformat"].create(
            {"name": "audit A3 portrait", "format": "A3", "orientation": "Portrait"}
        )
        self.assertAlmostEqual(pf.print_page_width, 297.0)
        self.assertAlmostEqual(pf.print_page_height, 420.0)
