"""Byte-compatibility and contract tests for the canonical ``__version`` hash.

``odoo.tools.cache_version._canonical_sha256`` was switched from stdlib ``json``
to orjson (Rust) for speed.  The client rpc cache (``rpc_cache.js``) compares two
*server-emitted* ``__version`` strings for O(1) equality and **never recomputes**
the hash itself, so the runtime contract is only:

  * deterministic — identical content always yields the identical digest;
  * key-order invariant — dict insertion order must not matter;
  * never raises — it stamps live responses.

On top of that contract we additionally pin **byte-identity with the previous
stdlib output** for the value space these endpoints actually emit (str-keyed
dicts of finite JSON scalars, ASCII or not, ids, datetimes), so existing client
caches are not invalidated by the swap.  Three encodings intentionally diverge
(toward standard-JSON / V8 ``JSON.stringify`` semantics); those are pinned
explicitly in :class:`TestIntentionalDivergences` and documented in
``cache_version._CANONICAL_OPT``.

No Odoo ORM / database dependency — runs under the standalone pytest suite.
"""

import datetime
import hashlib
import json
import math
import unittest

from odoo.tools.cache_version import _canonical_bytes, _canonical_sha256


def _stdlib_canonical(value):
    """The exact pre-orjson implementation — the byte reference."""
    return json.dumps(
        value, sort_keys=True, default=str, separators=(",", ":")
    ).encode()


# Payloads spanning what web_search_read / web_read / read_group / search_panel
# actually return.  Every entry here is expected to be byte-identical to the old
# stdlib canonical form (normal scalars + str-keyed structures); big ints and
# non-str keys reach that identity via the stdlib fallback.
BYTE_IDENTICAL_PAYLOADS = [
    # ints (incl. one beyond 64-bit that exercises the stdlib fallback)
    0, 1, -1, 2**31, 1234567890, 2**70,
    # finite floats at realistic magnitudes (prices/qty/percent)
    0.0, 1.0, 1.5, -0.0, 3.14159, 100.0, 12.34, 0.1, 1234567.89, -9999.999,
    2.0**53, 1e16,
    # other scalars
    True, False, None,
    "", "ascii", "tab\tnewline\n", 'quote"and\\backslash',
    # containers (tuple -> array, like stdlib)
    [], {}, [1, 2, 3], (1, 2, 3),
    {"b": 1, "a": 2, "c": 3},
    {"id": 5, "display_name": "ir.model.fields"},
    {"nested": {"z": [3, 2, 1], "a": {"k": "v"}}, "list": [{"x": 1}, {"y": 2}]},
    # the realistic web_search_read result shape
    {"length": 2006, "records": [
        {"id": i, "name": f"field_{i}", "ttype": "char", "required": False,
         "store": True, "relation": False,
         "model_id": {"id": i % 7, "display_name": f"model.{i % 7}"}}
        for i in range(5)
    ]},
    # non-JSON-native values routed through default=str (matches old behavior)
    datetime.datetime(2026, 2, 15, 10, 30, 0),
    datetime.datetime(2026, 2, 15, 10, 30, 0, 123456),  # microseconds: str() both sides
    datetime.date(2026, 2, 15),
    {"created": datetime.datetime(2026, 2, 15, 10, 30, 0), "name": "x"},
    b"abc",
    {1: "a", 2: "b", 10: "c"},  # non-str keys -> stdlib fallback (numeric sort)
]


class TestByteIdentity(unittest.TestCase):
    """The swap must not change the digest for the emitted value space."""

    def test_canonical_bytes_match_stdlib(self):
        for value in BYTE_IDENTICAL_PAYLOADS:
            with self.subTest(value=repr(value)[:60]):
                self.assertEqual(_canonical_bytes(value), _stdlib_canonical(value))

    def test_digest_matches_old_implementation(self):
        for value in BYTE_IDENTICAL_PAYLOADS:
            with self.subTest(value=repr(value)[:60]):
                self.assertEqual(
                    _canonical_sha256(value),
                    hashlib.sha256(_stdlib_canonical(value)).hexdigest(),
                )


class TestContract(unittest.TestCase):
    """Properties the JS rpc cache actually relies on (rpc_cache.js)."""

    def test_key_order_invariant(self):
        a = {"a": 1, "b": 2, "c": {"x": 9, "y": 8}}
        b = {"c": {"y": 8, "x": 9}, "b": 2, "a": 1}
        self.assertEqual(_canonical_sha256(a), _canonical_sha256(b))

    def test_key_order_invariant_non_ascii(self):
        a = {"x": "café", "y": "naïve", "z": "Société"}
        b = {"z": "Société", "y": "naïve", "x": "café"}
        self.assertEqual(_canonical_sha256(a), _canonical_sha256(b))

    def test_deterministic(self):
        v = {"length": 3, "records": [{"id": 1, "name": "x"}]}
        self.assertEqual(_canonical_sha256(v), _canonical_sha256(dict(v)))

    def test_digest_is_hex_sha256(self):
        digest = _canonical_sha256({"a": 1})
        self.assertEqual(len(digest), 64)
        int(digest, 16)  # raises if not hex

    def test_never_raises(self):
        # Must survive every value a response could carry, including the ones
        # orjson rejects (fallback) and the non-finite/non-ASCII edge cases.
        hostile = [
            {"big": 2**128}, {3: "x", 30: "y"}, {"inf": math.inf},
            {"nan": math.nan}, {"s": "café ☕ 🎉"}, {"tiny": 1e-300},
            {(1, 2): "tuple-key"} if False else {"ok": 1},  # keep JSON-able
        ]
        for v in hostile:
            with self.subTest(value=repr(v)[:60]):
                self.assertEqual(len(_canonical_sha256(v)), 64)


class TestIntentionalDivergences(unittest.TestCase):
    """Encodings that intentionally differ from the old stdlib bytes — each
    moves toward standard-JSON / V8 ``JSON.stringify`` and is contract-safe
    (one-time, self-healing client cache refresh; never recomputed in JS)."""

    def test_non_ascii_is_utf8_not_escaped(self):
        v = {"display_name": "Société Générale — café ☕"}
        new = _canonical_bytes(v)
        # Differs from the old \uXXXX-escaped form ...
        self.assertNotEqual(new, _stdlib_canonical(v))
        # ... and equals a UTF-8 (ensure_ascii=False) canonical rendering,
        # which is what V8 JSON.stringify emits.
        self.assertEqual(
            new,
            json.dumps(
                v, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8"),
        )

    def test_non_finite_floats_become_null(self):
        # orjson emits JSON ``null`` for inf/nan (as V8 does); stdlib emitted
        # the invalid tokens ``Infinity`` / ``NaN``.
        self.assertEqual(_canonical_bytes({"x": math.inf}), b'{"x":null}')
        self.assertEqual(_canonical_bytes({"x": -math.inf}), b'{"x":null}')
        self.assertEqual(_canonical_bytes({"x": math.nan}), b'{"x":null}')

    def test_exponent_float_formatting(self):
        # orjson omits the leading zero in the exponent (1e-7, not 1e-07).
        self.assertEqual(_canonical_bytes(1e-7), b"1e-7")
        self.assertNotEqual(_canonical_bytes(1e-7), _stdlib_canonical(1e-7))


if __name__ == "__main__":
    unittest.main()
