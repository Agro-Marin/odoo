from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.base.models.report_paperformat import (
    PAPER_SIZE_BY_KEY,
    PAPER_SIZES,
)

A4_WIDTH = 210.0
A4_HEIGHT = 297.0


@tagged("post_install", "-at_install")
class TestReportPaperformatAudit(TransactionCase):
    def test_a4_portrait_dimensions(self):
        pf = self.env["report.paperformat"].create(
            {"name": "audit A4 portrait", "format": "A4", "orientation": "Portrait"}
        )
        self.assertAlmostEqual(pf.print_page_width, A4_WIDTH)
        self.assertAlmostEqual(pf.print_page_height, A4_HEIGHT)

    def test_a4_landscape_dimensions_swapped(self):
        pf = self.env["report.paperformat"].create(
            {"name": "audit A4 landscape", "format": "A4", "orientation": "Landscape"}
        )
        self.assertAlmostEqual(pf.print_page_width, A4_HEIGHT)
        self.assertAlmostEqual(pf.print_page_height, A4_WIDTH)

    def test_custom_format_honors_explicit_dimensions(self):
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

    def test_print_page_size_recomputed_on_orientation_change(self):
        pf = self.env["report.paperformat"].create(
            {"name": "audit reorient", "format": "A4", "orientation": "Portrait"}
        )
        self.assertAlmostEqual(pf.print_page_width, A4_WIDTH)
        pf.orientation = "Landscape"
        self.assertAlmostEqual(pf.print_page_width, A4_HEIGHT)
        self.assertAlmostEqual(pf.print_page_height, A4_WIDTH)

    def test_print_page_size_recomputed_on_format_change(self):
        pf = self.env["report.paperformat"].create(
            {"name": "audit reformat", "format": "A4", "orientation": "Portrait"}
        )
        self.assertAlmostEqual(pf.print_page_height, A4_HEIGHT)
        pf.format = "A5"
        a5 = PAPER_SIZE_BY_KEY["A5"]
        self.assertAlmostEqual(pf.print_page_width, a5["width"])
        self.assertAlmostEqual(pf.print_page_height, a5["height"])

    def test_print_page_size_recomputed_on_custom_dimension_change(self):
        pf = self.env["report.paperformat"].create(
            {
                "name": "audit recustom",
                "format": "custom",
                "orientation": "Portrait",
                "page_width": 150,
                "page_height": 250,
            }
        )
        self.assertAlmostEqual(pf.print_page_width, 150)
        pf.page_width = 160
        self.assertAlmostEqual(pf.print_page_width, 160)

    def test_named_format_with_page_dimensions_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["report.paperformat"].create(
                {
                    "name": "audit A4 with width",
                    "format": "A4",
                    "page_width": 100,
                }
            )

    def test_default_field_dropped(self):
        self.assertNotIn("default", self.env["report.paperformat"]._fields)

    def test_paper_size_key_map_matches_list(self):
        self.assertEqual(len(PAPER_SIZE_BY_KEY), len(PAPER_SIZES))
        for paper_size in PAPER_SIZES:
            self.assertIs(PAPER_SIZE_BY_KEY[paper_size["key"]], paper_size)

    def test_non_a4_named_format_dimensions(self):
        pf = self.env["report.paperformat"].create(
            {"name": "audit A3 portrait", "format": "A3", "orientation": "Portrait"}
        )
        self.assertAlmostEqual(pf.print_page_width, 297.0)
        self.assertAlmostEqual(pf.print_page_height, 420.0)
