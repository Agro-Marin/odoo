import unittest

import odoo.tools.safe_eval as se


class TestValidatedBytecodeCacheEviction(unittest.TestCase):
    def setUp(self):
        self._saved_cache = dict(se._validated_bytecode_cache)
        self._saved_max = se._VALIDATED_CACHE_MAX
        se._validated_bytecode_cache.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        se._validated_bytecode_cache.clear()
        se._validated_bytecode_cache.update(self._saved_cache)
        se._VALIDATED_CACHE_MAX = self._saved_max

    def test_cache_stays_bounded_and_keeps_accepting(self):
        se._VALIDATED_CACHE_MAX = 16
        for i in range(200):
            se.expr_eval(f"{i} + {i}")
        self.assertLessEqual(
            len(se._validated_bytecode_cache),
            se._VALIDATED_CACHE_MAX,
            "cache must never exceed its cap",
        )
        self.assertEqual(
            len(se._validated_bytecode_cache),
            se._VALIDATED_CACHE_MAX,
            "a full cache must stay full (evict + insert), not stop inserting",
        )

    def test_recent_entry_is_cached(self):
        se._VALIDATED_CACHE_MAX = 8
        for i in range(50):
            se.expr_eval(f"{i} * 2")
        before = len(se._validated_bytecode_cache)
        se.expr_eval("49 * 2")
        self.assertEqual(len(se._validated_bytecode_cache), before)


if __name__ == "__main__":
    unittest.main()
