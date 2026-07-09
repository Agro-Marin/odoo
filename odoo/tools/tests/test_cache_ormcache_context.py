"""Regression test for ``odoo.tools.cache.ormcache_context``.

Applying the decorator must not crash: ``determine_key`` reads ``self.keys``,
which ``__init__`` has to store.  This exercises decoration only (no registry),
so it stays database-free.
"""

import unittest
import warnings

from odoo.tools.cache import ormcache_context


class TestOrmcacheContext(unittest.TestCase):
    def test_decoration_does_not_crash(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            decorator = ormcache_context("a", keys=("lang", "company"))

            def method(self, a, context=None):
                return a

            # Regression: this used to raise AttributeError: no attribute 'keys'.
            wrapped = decorator(method)

        self.assertTrue(hasattr(wrapped, "__cache__"))
        self.assertEqual(decorator.keys, ("lang", "company"))

    def test_context_keys_folded_into_key(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            decorator = ormcache_context("a", keys=("lang",))

            def method(self, a, context=None):
                return a

            decorator(method)

        # The context lookup expression must reference the requested keys.
        self.assertTrue(any("lang" in str(arg) for arg in decorator.args))


if __name__ == "__main__":
    unittest.main()
