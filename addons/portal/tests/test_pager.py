from odoo.tests.common import TransactionCase

from odoo.addons.portal.controllers.portal import pager


class TestPager(TransactionCase):
    def test_pager_functionality(self):
        """Test the custom pager functionality."""
        test_cases = [
            # Case 1: Total items fit in one page
            {"total": 20, "page": 1, "expected_pages": [1]},
            # Case 2: Exactly two pages, first page active
            {"total": 50, "page": 1, "expected_pages": [1, 2]},
            # Case 3: Exactly five pages, middle page active
            {"total": 150, "page": 3, "expected_pages": [1, 2, 3, 4, 5]},
            # Case 4: Large number of pages, ellipses in the middle
            {"total": 300, "page": 5, "expected_pages": [1, "…", 4, 5, 6, "…", 10]},
            # Case 5: Large number of pages, first page active
            {"total": 300, "page": 1, "expected_pages": [1, 2, 3, 4, "…", 10]},
            # Case 6: Large number of pages, last page active
            {"total": 300, "page": 10, "expected_pages": [1, "…", 7, 8, 9, 10]},
        ]
        for case in test_cases:
            result = pager(
                url=case.get("url", "/test"),
                total=case["total"],
                page=case["page"],
                step=30,
                scope=5,
                url_args=None,
            )

            # Calculate expected page count
            expected_page_count = (case["total"] + 30 - 1) // 30
            pages = [p["num"] for p in result["pages"]]

            # Assertions
            with self.subTest(case=case):
                self.assertEqual(
                    pages,
                    case["expected_pages"],
                    f"Expected pages mismatch for case: {case}",
                )
                self.assertEqual(
                    result["page"]["num"],
                    case["page"],
                    f"Current page mismatch for case: {case}",
                )
                self.assertEqual(
                    result["page_count"],
                    expected_page_count,
                    f"Page count mismatch for case: {case}",
                )

    def test_pager_scope_is_honoured(self):
        """`scope` controls the width of the dense page window.

        Regression guard: `scope` was silently ignored (a fixed 5-wide window)
        for a long time; callers such as website_slides (scope=3) and
        website_crm_partner_assign (scope=7) rely on it. `scope=5` must stay
        byte-identical to the historical output (verified here on the
        representative middle-page case).
        """
        # 10 pages (total=300, step=30), current page 5 in the middle.
        common = {"url": "/test", "total": 300, "page": 5, "step": 30}
        cases = [
            # scope: expected page numbers (… = ellipsis)
            (3, [1, "…", 5, "…", 10]),
            (5, [1, "…", 4, 5, 6, "…", 10]),  # unchanged historical default
            (7, [1, 2, 3, 4, 5, 6, "…", 10]),
        ]
        for scope, expected in cases:
            with self.subTest(scope=scope):
                pages = [p["num"] for p in pager(**common, scope=scope)["pages"]]
                self.assertEqual(pages, expected)

    def test_pager_scope_below_minimum_does_not_degenerate(self):
        """scope < 3 is clamped so the centred window never collapses to empty."""
        pages = [
            p["num"]
            for p in pager("/test", total=300, page=5, step=30, scope=1)["pages"]
        ]
        # No empty run between the two ellipses; current page is present.
        self.assertIn(5, pages)
        self.assertEqual(pages[0], 1)
        self.assertEqual(pages[-1], 10)
