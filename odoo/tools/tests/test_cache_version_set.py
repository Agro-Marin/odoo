"""Regression tests: ``__version`` digests must be stable for set payloads.

``set``/``frozenset`` have no defined iteration order; the previous coercion
``default=str`` emitted ``str(set)``, whose order depends on ``PYTHONHASHSEED``
(randomized per process). Two workers therefore produced *different* digests for
identical data, making the client rpc cache treat every worker-to-worker
revalidation as "changed" and refetch — defeating the whole point of the stamp.

The canonical form now emits unordered collections as a deterministically
ordered JSON array. These tests pin that contract. The cross-*process* stability
(the actual bug) is covered by the workspace audit; here we pin the two
consequences observable in-process: order-invariance and array shape.

No Odoo ORM / database dependency — runs under the standalone pytest suite.
"""

import unittest

from odoo.tools.cache_version import _canonical_bytes


class TestSetDigestStability(unittest.TestCase):
    def test_set_serializes_as_sorted_array(self):
        self.assertEqual(
            _canonical_bytes({"gamma", "alpha", "beta"}),
            b'["alpha","beta","gamma"]',
        )

    def test_frozenset_matches_set(self):
        self.assertEqual(
            _canonical_bytes(frozenset({"b", "a"})),
            _canonical_bytes({"a", "b"}),
        )

    def test_insertion_order_does_not_change_digest(self):
        # Two sets with the same members but built in different orders must hash
        # identically (the property PYTHONHASHSEED randomization used to break).
        s1 = set()
        for e in ("alpha", "beta", "gamma", "delta", "epsilon"):
            s1.add(e)
        s2 = set()
        for e in ("epsilon", "delta", "gamma", "beta", "alpha"):
            s2.add(e)
        self.assertEqual(_canonical_bytes(s1), _canonical_bytes(s2))

    def test_int_set_is_ordered(self):
        self.assertEqual(_canonical_bytes({3, 1, 2}), b"[1,2,3]")

    def test_set_nested_in_dict_is_stable(self):
        a = {"tags": {"z", "a", "m"}, "id": 1}
        b = {"id": 1, "tags": {"m", "a", "z"}}
        self.assertEqual(_canonical_bytes(a), _canonical_bytes(b))


if __name__ == "__main__":
    unittest.main()
