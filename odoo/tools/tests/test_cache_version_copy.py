"""``@versioned`` must not mutate the dict the wrapped method returned.

The stamp is derived from the dict's own contents, so writing ``__version`` back
into the same object (a) would corrupt a shared/cached return value -- and its
documented "already has ``__version`` -> no-op" branch would then pin that first
digest forever -- and (b) leaves the returned dict no longer hashing to its own
stamp.  The decorator now returns a shallow copy carrying the stamp.
"""

import unittest

from odoo.tools.cache_version import versioned


class TestVersionedDoesNotMutateSource(unittest.TestCase):
    def test_source_dict_is_not_mutated(self):
        source = {"a": 1, "b": 2}

        @versioned
        def method(self):
            return source

        result = method(None)
        self.assertIn("__version", result)
        self.assertNotIn(
            "__version", source, "the method's own dict must stay untouched"
        )
        self.assertIsNot(result, source)

    def test_idempotent_when_version_present(self):
        @versioned
        def method(self):
            return {"a": 1, "__version": "preset"}

        self.assertEqual(method(None)["__version"], "preset")

    def test_non_dict_passthrough(self):
        @versioned
        def method(self):
            return [1, 2, 3]

        self.assertEqual(method(None), [1, 2, 3])

    def test_stamp_is_stable_for_equal_payloads(self):
        @versioned
        def method(self, payload):
            return dict(payload)

        v1 = method(None, {"x": 1, "y": 2})["__version"]
        v2 = method(None, {"y": 2, "x": 1})["__version"]
        self.assertEqual(v1, v2, "digest must be insertion-order invariant")


if __name__ == "__main__":
    unittest.main()
