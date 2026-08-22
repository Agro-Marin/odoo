import odoo.tests
from odoo.tests.common import BaseCase

from odoo.addons.html_editor.models.diff_utils import (
    apply_patch,
    generate_comparison,
    generate_patch,
    generate_unified_diff,
)


@odoo.tests.tagged("post_install", "-at_install", "html_history")
class TestUnnecessaryReplaceFixer(BaseCase):
    def test_collapse_single_character(self):
        self.assertEqual(
            generate_comparison("<div class='B1'>A</div>", "<div class='A1'>A</div>"),
            "<div class='A1'>A</div>",
        )

    def test_collapse_multi_character(self):
        self.assertEqual(
            generate_comparison(
                "<div class='B1'>Abc</div>", "<div class='A1'>Abc</div>"
            ),
            "<div class='A1'>Abc</div>",
        )

    def test_collapse_docstring_example(self):
        self.assertEqual(
            generate_comparison("<p class='y'>abc</p>", "<p class='x'>abc</p>"),
            "<p class='x'>abc</p>",
        )

    def test_does_not_collapse_when_text_differs(self):
        self.assertEqual(
            generate_comparison("<p class='y'>abc</p>", "<p class='x'>xyz</p>"),
            "<p class='x'><added>xyz</added><removed>abc</removed></p>",
        )

    def test_does_not_collapse_across_elements(self):
        comparison = generate_comparison(
            "<p>abc</p><p>def</p>", "<p>xyz</p><p>uvw</p>"
        )
        self.assertIn("<added>xyz</added><removed>abc</removed>", comparison)
        self.assertIn("<added>uvw</added><removed>def</removed>", comparison)

    def test_whole_document_attribute_change_is_not_noise(self):
        new = "".join(f"<p class='b{i}'>paragraph {i} text</p>" for i in range(30))
        old = "".join(f"<p class='a{i}'>paragraph {i} text</p>" for i in range(30))
        comparison = generate_comparison(new, old)
        self.assertNotIn("<added>", comparison)
        self.assertNotIn("<removed>", comparison)


@odoo.tests.tagged("post_install", "-at_install", "html_history")
class TestApplyPatchRobustness(BaseCase):
    def test_malformed_metadata_without_index(self):
        self.assertEqual(apply_patch("<p>a</p>", "+"), "<p>a</p>")

    def test_non_numeric_index(self):
        self.assertEqual(apply_patch("<p>a</p>", "-@abc"), "<p>a</p>")

    def test_out_of_range_index(self):
        self.assertEqual(apply_patch("<p>a</p>", "-@99"), "<p>a</p>")

    def test_inverted_range(self):
        self.assertEqual(apply_patch("<p>a</p><p>b</p>", "-@3,1"), "<p>a</p><p>b</p>")

    def test_insert_at_start_still_works(self):
        old = "<p>first</p><p>second</p>"
        new = "<p>second</p>"
        patch = generate_patch(new, old)
        self.assertEqual(apply_patch(new, patch), old)

    def test_empty_patch_is_identity(self):
        self.assertEqual(apply_patch("<p>a</p>", ""), "<p>a</p>")


@odoo.tests.tagged("post_install", "-at_install", "html_history")
class TestPatchRoundTrip(BaseCase):
    def _assert_round_trip(self, new, old):
        patch = generate_patch(new, old)
        self.assertEqual(apply_patch(new, patch), old)

    def test_round_trip_attribute_only_change(self):
        new = "".join(f"<p class='b{i}'>paragraph {i} text</p>" for i in range(60))
        old = "".join(f"<p class='a{i}'>paragraph {i} text</p>" for i in range(60))
        self._assert_round_trip(new, old)

    def test_round_trip_single_word_change(self):
        old = "".join(f"<p>paragraph {i} text</p>" for i in range(60))
        new = old.replace("paragraph 5 ", "paragraph 5 EDITED ")
        self._assert_round_trip(new, old)

    def test_round_trip_full_replacement(self):
        old = "".join(f"<p>old {i}</p>" for i in range(40))
        new = "".join(f"<div>new {i}</div>" for i in range(40))
        self._assert_round_trip(new, old)

    def test_round_trip_from_empty(self):
        self._assert_round_trip("", "".join(f"<p>{i}</p>" for i in range(20)))

    def test_round_trip_to_empty(self):
        self._assert_round_trip("".join(f"<p>{i}</p>" for i in range(20)), "")

    def test_many_repeated_tokens_completes_quickly(self):
        import time

        new = "".join(f"<p class='b{i}'>paragraph {i} text here</p>" for i in range(400))
        old = "".join(f"<p class='a{i}'>paragraph {i} text here</p>" for i in range(400))
        start = time.monotonic()
        patch = generate_patch(new, old)
        elapsed = time.monotonic() - start
        self.assertEqual(apply_patch(new, patch), old)
        self.assertLess(elapsed, 0.5, "generate_patch regressed to the quadratic path")


@odoo.tests.tagged("post_install", "-at_install", "html_history")
class TestUnifiedDiffFormat(BaseCase):
    def test_headers_have_no_doubled_line_terminators(self):
        diff = generate_unified_diff("<p>b</p>", "<p>a</p>")
        self.assertNotIn("\n\n", diff)
        self.assertIn("--- old", diff)
        self.assertIn("+++ new", diff)
