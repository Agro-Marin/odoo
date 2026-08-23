"""``@ormcache`` must refuse a keyword it does not understand.

``cache=`` was validated against ``REGISTRY_CACHES`` and rejected loudly, while
``**kwargs`` swallowed everything else -- so ``cache='nope'`` raised and
``cach='stable'`` silently produced a decorator on the ``default`` bucket. The
buckets are not interchangeable: each exists because its invalidation cadence
differs, so a misspelling is a cache invalidated on the wrong signal, not a
cosmetic slip.

An AST sweep of all four repositories found no such typo in the tree, which is
exactly why this is worth pinning: nothing else would notice the first one.
"""

import unittest

from odoo.tools.cache import ormcache, ormcache_context


class TestOrmcacheUnknownKwargs(unittest.TestCase):
    def test_known_bucket_is_accepted(self):
        self.assertEqual(ormcache("self.id", cache="stable").cache_name, "stable")

    def test_default_bucket_is_the_default(self):
        self.assertEqual(ormcache("self.id").cache_name, "default")

    def test_unknown_bucket_still_raises(self):
        with self.assertRaises(ValueError) as caught:
            ormcache("self.id", cache="nope")
        self.assertIn("unknown cache", str(caught.exception))

    def test_a_misspelt_cache_keyword_raises(self):
        for typo in ("cach", "chache", "caches"):
            with self.subTest(typo=typo), self.assertRaises(TypeError):
                ormcache("self.id", **{typo: "stable"})

    def test_an_invented_keyword_raises(self):
        with self.assertRaises(TypeError):
            ormcache("self.id", lru_size=99)

    def test_ormcache_context_does_not_reopen_the_hole(self):
        with self.assertRaises(TypeError):
            ormcache_context("self.id", keys=("lang",), cach="stable")


# Defined at module level on purpose: an identifier starting with two
# underscores is mangled inside a class body, which would rename the parameter
# these tests are about before the decorator ever sees it.
def _shadows_the_method(self, __ormcache_method, value):
    return value


def _shadows_a_default(self, __ormcache_default_0, value=1):
    return value


class TestOrmcacheKeyShadowing(unittest.TestCase):
    """The key expression names the decorated function -- and each defaulted
    parameter -- through a global. A parameter of the same name would shadow it,
    and the cache would key on the *argument* instead, so two different methods
    called with the same value would share an entry.
    """

    def test_a_parameter_cannot_shadow_the_method(self):
        with self.assertRaises(ValueError) as caught:
            ormcache("value")(_shadows_the_method)
        self.assertIn("reserved", str(caught.exception))

    def test_a_parameter_cannot_shadow_a_generated_default(self):
        with self.assertRaises(ValueError):
            ormcache("value")(_shadows_a_default)

    def test_an_ordinary_signature_is_unaffected(self):
        def compute(self, value, flag=True):
            return value

        key = ormcache("value")(compute).__cache__.key
        self.assertTrue(callable(key))


if __name__ == "__main__":
    unittest.main()
