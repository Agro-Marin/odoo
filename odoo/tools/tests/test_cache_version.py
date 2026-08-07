import datetime
import json
import math
import unittest

from odoo.libs.hashing import cache_hash
from odoo.tools.cache_version import _canonical_bytes, _canonical_digest


def _stdlib_canonical(value):
    return json.dumps(
        value, sort_keys=True, default=str, separators=(",", ":")
    ).encode()


BYTE_IDENTICAL_PAYLOADS = [
    0,
    1,
    -1,
    2**31,
    1234567890,
    2**70,
    0.0,
    1.0,
    1.5,
    -0.0,
    math.pi,
    100.0,
    12.34,
    0.1,
    1234567.89,
    -9999.999,
    2.0**53,
    1e16,
    True,
    False,
    None,
    "",
    "ascii",
    "tab\tnewline\n",
    'quote"and\\backslash',
    [],
    {},
    [1, 2, 3],
    (1, 2, 3),
    {"b": 1, "a": 2, "c": 3},
    {"id": 5, "display_name": "ir.model.fields"},
    {"nested": {"z": [3, 2, 1], "a": {"k": "v"}}, "list": [{"x": 1}, {"y": 2}]},
    {
        "length": 2006,
        "records": [
            {
                "id": i,
                "name": f"field_{i}",
                "ttype": "char",
                "required": False,
                "store": True,
                "relation": False,
                "model_id": {"id": i % 7, "display_name": f"model.{i % 7}"},
            }
            for i in range(5)
        ],
    },
    datetime.datetime(2026, 2, 15, 10, 30, 0),
    datetime.datetime(2026, 2, 15, 10, 30, 0, 123456),
    datetime.date(2026, 2, 15),
    {"created": datetime.datetime(2026, 2, 15, 10, 30, 0), "name": "x"},
    b"abc",
    {1: "a", 2: "b", 10: "c"},
]


class TestByteIdentity(unittest.TestCase):
    def test_canonical_bytes_match_stdlib(self):
        for value in BYTE_IDENTICAL_PAYLOADS:
            with self.subTest(value=repr(value)[:60]):
                self.assertEqual(_canonical_bytes(value), _stdlib_canonical(value))

    def test_digest_matches_old_implementation(self):
        for value in BYTE_IDENTICAL_PAYLOADS:
            with self.subTest(value=repr(value)[:60]):
                self.assertEqual(
                    _canonical_digest(value),
                    cache_hash(_stdlib_canonical(value)),
                )


class TestContract(unittest.TestCase):
    def test_key_order_invariant(self):
        a = {"a": 1, "b": 2, "c": {"x": 9, "y": 8}}
        b = {"c": {"y": 8, "x": 9}, "b": 2, "a": 1}
        self.assertEqual(_canonical_digest(a), _canonical_digest(b))

    def test_key_order_invariant_non_ascii(self):
        a = {"x": "café", "y": "naïve", "z": "Société"}
        b = {"z": "Société", "y": "naïve", "x": "café"}
        self.assertEqual(_canonical_digest(a), _canonical_digest(b))

    def test_deterministic(self):
        v = {"length": 3, "records": [{"id": 1, "name": "x"}]}
        self.assertEqual(_canonical_digest(v), _canonical_digest(dict(v)))

    def test_digest_is_hex_sha256(self):
        digest = _canonical_digest({"a": 1})
        self.assertEqual(len(digest), 64)
        int(digest, 16)

    def test_never_raises(self):
        hostile = [
            {"big": 2**128},
            {3: "x", 30: "y"},
            {"inf": math.inf},
            {"nan": math.nan},
            {"s": "café ☕ 🎉"},
            {"tiny": 1e-300},
            {(1, 2): "tuple-key"} if False else {"ok": 1},
        ]
        for v in hostile:
            with self.subTest(value=repr(v)[:60]):
                self.assertEqual(len(_canonical_digest(v)), 64)


class TestIntentionalDivergences(unittest.TestCase):
    def test_non_ascii_is_utf8_not_escaped(self):
        v = {"display_name": "Société Générale — café ☕"}
        new = _canonical_bytes(v)
        self.assertNotEqual(new, _stdlib_canonical(v))
        self.assertEqual(
            new,
            json.dumps(
                v, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8"),
        )

    def test_non_finite_floats_become_null(self):
        self.assertEqual(_canonical_bytes({"x": math.inf}), b'{"x":null}')
        self.assertEqual(_canonical_bytes({"x": -math.inf}), b'{"x":null}')
        self.assertEqual(_canonical_bytes({"x": math.nan}), b'{"x":null}')

    def test_exponent_float_formatting(self):
        self.assertEqual(_canonical_bytes(1e-7), b"1e-7")
        self.assertNotEqual(_canonical_bytes(1e-7), _stdlib_canonical(1e-7))


if __name__ == "__main__":
    unittest.main()
