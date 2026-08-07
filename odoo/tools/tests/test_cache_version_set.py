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
        s1 = set()
        s1.update(("alpha", "beta", "gamma", "delta", "epsilon"))
        s2 = set()
        s2.update(("epsilon", "delta", "gamma", "beta", "alpha"))
        self.assertEqual(_canonical_bytes(s1), _canonical_bytes(s2))

    def test_int_set_is_ordered(self):
        self.assertEqual(_canonical_bytes({3, 1, 2}), b"[1,2,3]")

    def test_set_nested_in_dict_is_stable(self):
        a = {"tags": {"z", "a", "m"}, "id": 1}
        b = {"id": 1, "tags": {"m", "a", "z"}}
        self.assertEqual(_canonical_bytes(a), _canonical_bytes(b))


if __name__ == "__main__":
    unittest.main()
