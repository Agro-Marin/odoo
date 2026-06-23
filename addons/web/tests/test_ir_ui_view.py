"""Tests for ``ir.ui.view`` web helpers (``models/ir_ui_view.py``)."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "web_unit")
class TestGetViewInfo(TransactionCase):
    """``get_view_info`` is ormcached; the key must be per-language.

    ``get_view_info`` returns ``display_name`` values taken from the ``type``
    field's selection labels, which ``fields_get`` translates per ``env.lang``.
    A language-independent cache key would serve the first caller's language to
    every other language until the cache is invalidated -- a real i18n bug a
    bare ``@ormcache()`` would reintroduce.
    """

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
        """Sanity check the helper still returns the expected shape."""
        info = self.env["ir.ui.view"].get_view_info()
        self.assertIn("form", info)
        self.assertIn("display_name", info["form"])
        # form is the canonical single-record view
        self.assertFalse(info["form"]["multi_record"])
        self.assertNotIn("qweb", info, "qweb view type must be excluded")
