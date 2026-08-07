# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged

from odoo.addons.base_credential_manager.tools.session_cache import (
    SessionCache,
    get_session_cache,
    invalidate_session_cache,
)


@tagged("post_install", "-at_install")
class TestSessionCacheHelpers(TransactionCase):
    """Registry-backed session cache accessors and selective invalidation."""

    def test_get_session_cache_returns_singleton(self):
        """The registry hands back the same cache instance across calls."""
        first = get_session_cache(self.env)
        second = get_session_cache(self.env)
        self.assertIs(first, second)

    def test_invalidate_matching_removes_only_matches(self):
        """invalidate_matching drops entries whose key matches the filter."""
        cache = SessionCache(max_size=10)
        cache.set("stripe:1", "a")
        cache.set("stripe:2", "b")
        cache.set("slack:1", "c")
        removed = cache.invalidate_matching(lambda key: key.startswith("stripe:"))
        self.assertEqual(removed, 2)
        self.assertIsNone(cache.get("stripe:1"))
        self.assertIsNotNone(cache.get("slack:1"))

    def test_invalidate_session_cache_clears_entries(self):
        """invalidate_session_cache empties the registry-backed cache."""
        cache = get_session_cache(self.env)
        cache.set("key", "value")
        invalidate_session_cache(self.env)
        self.assertIsNone(cache.get("key"))
