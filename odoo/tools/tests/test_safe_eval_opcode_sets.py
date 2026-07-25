"""The safe_eval opcode allowlists are immutable, and the validator's fast path
does not pay for a cache key it cannot use.

Two properties of ``assert_valid_codeobj`` are pinned here:

* the allowed-opcode sets are ``frozenset``.  They go into the validation cache
  key as ``frozenset(allowed_codes)`` on *every* call -- rebuilding + hashing ~90
  ints out of a plain ``set`` was two thirds of the cache-hit path, on the
  domain / QWeb / server-action hot path.  ``frozenset(x) is x`` for a frozenset,
  and a frozenset memoizes its hash, so both collapse to nothing.  It also makes
  the sandbox allowlist genuinely unmodifiable, which is the right contract.
* a code object containing a nested code object (any lambda) is never cached --
  its verdict is not captured by the parent's key -- so it must not build one.

Neither is observable through behaviour alone, hence the structural assertions;
the behavioural half (nested lambdas are still fully validated) is asserted too,
because that is what the no-caching rule protects.
"""

import unittest

from odoo.tools.safe_eval import (
    _BLACKLIST,
    _CONST_OPCODES,
    _EXPR_OPCODES,
    _SAFE_OPCODES,
    _validated_bytecode_cache,
    assert_valid_codeobj,
    compile_codeobj,
    const_eval,
    expr_eval,
    safe_eval,
)


class TestOpcodeSetsAreFrozen(unittest.TestCase):
    def test_every_allowlist_is_a_frozenset(self):
        for name, opcodes in (
            ("_BLACKLIST", _BLACKLIST),
            ("_CONST_OPCODES", _CONST_OPCODES),
            ("_EXPR_OPCODES", _EXPR_OPCODES),
            ("_SAFE_OPCODES", _SAFE_OPCODES),
        ):
            with self.subTest(name=name):
                self.assertIsInstance(opcodes, frozenset)
                self.assertFalse(hasattr(opcodes, "add"))

    def test_frozenset_of_an_allowlist_is_the_allowlist(self):
        """This identity is what makes the per-call cache key cheap."""
        self.assertIs(frozenset(_SAFE_OPCODES), _SAFE_OPCODES)

    def test_sets_derived_from_the_allowlists_stay_frozen(self):
        """``ir_qweb._SAFE_QWEB_OPCODES`` is built exactly this way."""
        derived = _EXPR_OPCODES.union({0}) - _BLACKLIST
        self.assertIsInstance(derived, frozenset)

    def test_blacklist_is_excluded_from_every_allowlist(self):
        for opcodes in (_CONST_OPCODES, _EXPR_OPCODES, _SAFE_OPCODES):
            self.assertFalse(opcodes & _BLACKLIST)


class TestNestedCodeIsNeverCached(unittest.TestCase):
    def test_the_parent_of_a_lambda_is_never_cached(self):
        """Only the *parent* is uncacheable.

        The inner lambda has no nested code of its own, so it caches normally --
        what must never appear is a verdict keyed on the enclosing code object,
        whose ``(co_code, co_names, ...)`` does not capture the lambda's body.
        """
        expr = "list(map(lambda r: r + 1, [1, 2, 3]))"
        code = compile_codeobj(expr)
        self.assertTrue(
            any(hasattr(c, "co_code") for c in code.co_consts),
            "test fixture must actually contain a nested code object",
        )

        assert_valid_codeobj(_SAFE_OPCODES, code, expr)
        assert_valid_codeobj(_SAFE_OPCODES, code, expr)

        parent_prefix = (code.co_code, code.co_names, code.co_consts)
        self.assertFalse(
            [key for key in _validated_bytecode_cache if key[:3] == parent_prefix],
            "the enclosing code object must not be cached",
        )

    def test_a_lambda_body_is_revalidated_on_every_call(self):
        """Two expressions with a byte-identical parent but different lambdas.

        This is the escape the no-caching rule closes: if the parent's verdict
        were cached, the second expression would inherit the first's "validated"
        and never have its ``__class__`` access rejected.
        """
        good = "list(map(lambda v: v.real, [1]))"
        bad = "list(map(lambda v: v.__class__, [1]))"
        good_code, bad_code = compile_codeobj(good), compile_codeobj(bad)
        self.assertEqual(good_code.co_code, bad_code.co_code)

        assert_valid_codeobj(_SAFE_OPCODES, good_code, good)
        with self.assertRaises(NameError):
            assert_valid_codeobj(_SAFE_OPCODES, bad_code, bad)

    def test_a_lambda_body_is_still_validated_every_time(self):
        """The reason nested code is never cached, asserted behaviourally."""
        for _round in range(2):
            with self.assertRaises(NameError):
                safe_eval("(lambda v: v.__class__)(1)")

    def test_plain_expression_is_cached(self):
        expr = "[('active', '=', True)]"
        code = compile_codeobj(expr)
        assert_valid_codeobj(_SAFE_OPCODES, code, expr)
        before = len(_validated_bytecode_cache)
        assert_valid_codeobj(_SAFE_OPCODES, code, expr)
        self.assertEqual(len(_validated_bytecode_cache), before)
        self.assertGreater(before, 0)


class TestEvaluatorsStillWork(unittest.TestCase):
    """End-to-end smoke tests over the three entry points, per allowlist."""

    def test_const_eval(self):
        self.assertEqual(const_eval("[1, 2, (3, 4), {'foo': 'bar'}]"), [1, 2, (3, 4), {"foo": "bar"}])
        with self.assertRaises(ValueError):
            const_eval("[1,2]*2")

    def test_expr_eval(self):
        self.assertEqual(expr_eval("[1,2]*2"), [1, 2, 1, 2])
        with self.assertRaises(NameError):
            expr_eval("__import__('sys').modules")

    def test_safe_eval(self):
        self.assertEqual(safe_eval("a + b", {"a": 1, "b": 2}), 3)
        self.assertEqual(
            safe_eval("[x * 2 for x in items]", {"items": [1, 2]}), [2, 4]
        )
        with self.assertRaises(NameError):
            safe_eval("obj.__class__", {"obj": object()})


if __name__ == "__main__":
    unittest.main()
