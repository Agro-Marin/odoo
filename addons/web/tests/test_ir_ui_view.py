from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "web_unit")
class TestGetViewInfo(TransactionCase):
    def test_cache_key_includes_language(self):
        View = self.env["ir.ui.view"]
        cache = type(View).get_view_info.__cache__
        key_en = cache.key(View.with_context(lang="en_US"))
        key_no_lang = cache.key(View.with_context(lang=None))
        self.assertIn(
            "en_US",
            key_en,
            "the resolved language must be part of the get_view_info cache key",
        )
        self.assertNotEqual(
            key_en,
            key_no_lang,
            "get_view_info cache key must differ across languages",
        )

    def test_returns_translatable_view_types(self):
        info = self.env["ir.ui.view"].get_view_info()
        self.assertIn("form", info)
        self.assertIn("display_name", info["form"])
        self.assertFalse(info["form"]["multi_record"])
        self.assertNotIn("qweb", info, "qweb view type must be excluded")

    def test_date_range_is_declared_by_the_type_and_not_shipped(self):
        # The /json route used to carry `("calendar", "gantt", "cohort")` as a
        # literal; a fourth date-ranged type was silently unfiltered. Each type
        # now declares it, and the client-facing dict does not grow a key for it.
        View = self.env["ir.ui.view"]
        self.assertTrue(View._view_type_has_date_range("calendar"))
        self.assertFalse(View._view_type_has_date_range("list"))
        self.assertFalse(View._view_type_has_date_range("no_such_type"))
        self.assertEqual(
            set(View.get_view_info()["calendar"]),
            {"display_name", "icon", "multi_record"},
        )
