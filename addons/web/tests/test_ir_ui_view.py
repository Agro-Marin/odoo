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
