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
        self.assertIs(frozenset(_SAFE_OPCODES), _SAFE_OPCODES)

    def test_sets_derived_from_the_allowlists_stay_frozen(self):
        derived = _EXPR_OPCODES.union({0}) - _BLACKLIST
        self.assertIsInstance(derived, frozenset)

    def test_blacklist_is_excluded_from_every_allowlist(self):
        for opcodes in (_CONST_OPCODES, _EXPR_OPCODES, _SAFE_OPCODES):
            self.assertFalse(opcodes & _BLACKLIST)


class TestBlacklistCannotSilentlyShrink(unittest.TestCase):
    def test_every_blacklisted_name_exists_on_this_interpreter(self):
        from odoo.tools.safe_eval import to_required_opcodes

        self.assertEqual(len(_BLACKLIST), len(list(to_required_opcodes(_NAMES))))

    def test_a_missing_blacklist_name_raises_instead_of_being_dropped(self):
        from odoo.tools.safe_eval import to_opcodes, to_required_opcodes

        bogus = ["IMPORT_NAME", "OPCODE_THAT_DOES_NOT_EXIST"]
        self.assertEqual(len(list(to_opcodes(bogus))), 1)
        with self.assertRaises(RuntimeError) as caught:
            list(to_required_opcodes(bogus))
        self.assertIn("OPCODE_THAT_DOES_NOT_EXIST", str(caught.exception))

    def test_import_star_is_still_blocked_by_import_name(self):
        import dis
        from opcode import opmap

        code = compile("from os import *", "<t>", "exec")
        emitted = {i.opname for i in dis.get_instructions(code)}
        self.assertIn("IMPORT_NAME", emitted)
        self.assertIn(opmap["IMPORT_NAME"], _BLACKLIST)


_NAMES = [
    "IMPORT_NAME",
    "IMPORT_FROM",
    "STORE_ATTR",
    "DELETE_ATTR",
    "STORE_GLOBAL",
    "DELETE_GLOBAL",
]


class TestNestedCodeIsNeverCached(unittest.TestCase):
    def test_the_parent_of_a_lambda_is_never_cached(self):
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
        good = "list(map(lambda v: v.real, [1]))"
        bad = "list(map(lambda v: v.__class__, [1]))"
        good_code, bad_code = compile_codeobj(good), compile_codeobj(bad)
        self.assertEqual(good_code.co_code, bad_code.co_code)

        assert_valid_codeobj(_SAFE_OPCODES, good_code, good)
        with self.assertRaises(NameError):
            assert_valid_codeobj(_SAFE_OPCODES, bad_code, bad)

    def test_a_lambda_body_is_still_validated_every_time(self):
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
    def test_const_eval(self):
        self.assertEqual(
            const_eval("[1, 2, (3, 4), {'foo': 'bar'}]"), [1, 2, (3, 4), {"foo": "bar"}]
        )
        with self.assertRaises(ValueError):
            const_eval("[1,2]*2")

    def test_expr_eval(self):
        self.assertEqual(expr_eval("[1,2]*2"), [1, 2, 1, 2])
        with self.assertRaises(NameError):
            expr_eval("__import__('sys').modules")

    def test_safe_eval(self):
        self.assertEqual(safe_eval("a + b", {"a": 1, "b": 2}), 3)
        self.assertEqual(safe_eval("[x * 2 for x in items]", {"items": [1, 2]}), [2, 4])
        with self.assertRaises(NameError):
            safe_eval("obj.__class__", {"obj": object()})


if __name__ == "__main__":
    unittest.main()
