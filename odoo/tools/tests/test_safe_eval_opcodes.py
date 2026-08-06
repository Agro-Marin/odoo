"""Regression tests for the ``odoo.tools.safe_eval`` opcode allowlist.

The allowlist is version-sensitive: ``to_opcodes()`` silently drops names absent
from the running interpreter's ``opmap``, so a CPython upgrade that renames or
introduces an opcode fails *closed* -- legitimate expressions start raising
``ValueError: forbidden opcode(s)`` with no other signal.  These tests pin the
constructs a server action is entitled to use, so that breakage shows up here
rather than in a customer's ``ir.actions.server``.

The second half pins the sandbox itself: every escape below must stay blocked.
Both halves matter together -- widening the allowlist is only safe while the
escapes still fail.
"""

import math
import unittest

from odoo.tools.safe_eval import assert_valid_codeobj, compile_codeobj, safe_eval

LEGITIMATE = {
    "try_except_finally": (
        "try:\n    result = 1\nexcept Exception:\n    result = 0\nfinally:\n    result += 10",
        11,
    ),
    "starred_unpacking": ("a, *rest = [1, 2, 3]\nresult = rest", [2, 3]),
    "del_subscript": ("d = {'a': 1, 'b': 2}\ndel d['a']\nresult = d", {"b": 2}),
    "nested_closure": (
        "def outer(a):\n"
        "    def inner(b):\n"
        "        return a + b\n"
        "    return inner\n"
        "result = outer(1)(2)",
        3,
    ),
    "yield_from": (
        "def gen():\n    yield from [1, 2, 3]\nresult = list(gen())",
        [1, 2, 3],
    ),
    "lambda_in_comprehension": (
        "result = [(lambda: x)() for x in [1, 2, 3]]",
        [1, 2, 3],
    ),
    "closure_mutation": (
        "def mk():\n"
        "    n = 0\n"
        "    def inc():\n"
        "        nonlocal n\n"
        "        n += 1\n"
        "        return n\n"
        "    return inc\n"
        "f = mk()\n"
        "f()\n"
        "result = f()",
        2,
    ),
}

ESCAPES = [
    "result = (1).__class__",
    "result = ().__class__.__bases__[0].__subclasses__()",
    "result = __import__('os')",
    "result = open('/etc/passwd')",
    "class C:\n    pass\nresult = C",
    "class C:\n    def f(self):\n        return __class__\nresult = C",
    "g = (x for x in [1])\nresult = g.gi_frame",
    "f = lambda: 1\nresult = f.func_code",
    "result = int.mro()",
]


class TestLegitimateConstructs(unittest.TestCase):
    def test_constructs_evaluate(self):
        for name, (code, expected) in LEGITIMATE.items():
            with self.subTest(construct=name):
                context = {}
                safe_eval(code, context, mode="exec")
                self.assertEqual(context.get("result"), expected)


class TestSandboxEscapesBlocked(unittest.TestCase):
    def test_escapes_raise(self):
        for code in ESCAPES:
            with self.subTest(escape=code.splitlines()[0]):
                with self.assertRaises((ValueError, NameError, TypeError)):
                    safe_eval(code, {}, mode="exec")


class TestSandboxEscapesNeedingContext(unittest.TestCase):
    """Escapes that need a populated context, so they cannot live in ESCAPES."""

    def test_module_hidden_in_dict_key_is_blocked(self):
        with self.assertRaises((TypeError, ValueError)):
            safe_eval("list(d)[0]", {"d": {math: 1}})

    def test_module_hidden_in_dict_value_is_blocked(self):
        with self.assertRaises((TypeError, ValueError)):
            safe_eval("list(d.values())[0]", {"d": {"m": math}})

    def test_str_format_reflection_escape_blocked(self):
        def gadget():
            pass

        escapes = [
            ('"{0.__class__.__mro__}".format(x)', {"x": 1}),
            ('"{0.__globals__}".format(f)', {"f": gadget}),
            ('"{x.__class__}".format_map({"x": 1})', {}),
            ('("{0.__cla" "ss__}").format(x)', {"x": 1}),
        ]
        for expr, ns in escapes:
            with self.subTest(escape=expr), self.assertRaises(Exception):
                safe_eval(expr, ns)

    def test_str_format_legitimate_uses_allowed(self):
        self.assertEqual(
            safe_eval('"hello {}".format(n)', {"n": "world"}), "hello world"
        )
        self.assertEqual(safe_eval('"{a}-{b}".format(a=1, b=2)', {}), "1-2")
        self.assertEqual(safe_eval('"{:,.2f}".format(x)', {"x": 1234.5}), "1,234.50")
        self.assertEqual(safe_eval('"{0[0]}-{0[1]}".format(p)', {"p": [7, 8]}), "7-8")

        # A model's own ``format`` method (res.currency / res.lang) is not
        # ``str.format`` and is left untouched.
        class FakeCurrency:
            def format(self, amount):
                return f"${amount}"

        self.assertEqual(safe_eval("c.format(v)", {"c": FakeCurrency(), "v": 9}), "$9")
        self.assertEqual(safe_eval('f"{a}-{b}"', {"a": 1, "b": 2}), "1-2")

    def test_str_format_attribute_navigation_is_forbidden(self):
        """Attribute access inside a ``str.format`` field is refused outright.

        ``"{0.real}".format(x)`` used to be allowed, but attribute navigation in
        a format field is exactly the pivot the reflection escape rides
        (``{0.__globals__}``, and — through ordinary public attributes —
        ``{0.env.cr.dbname}`` on a recordset). The two are indistinguishable
        statically, no eval-reachable code in the tree uses attribute
        navigation in a format field, so it is closed rather than sniffed.
        Index access, positional/keyword fields and format specs are unaffected
        (see :meth:`test_str_format_legitimate_uses_allowed`).
        """
        for expr, ns in (
            ('"{0.real}".format(x)', {"x": 5}),
            ('"{0.env}".format(r)', {"r": object()}),
        ):
            with self.subTest(expr=expr), self.assertRaises(Exception):
                safe_eval(expr, ns)

    def test_time_sleep_not_exposed(self):
        from odoo.tools.safe_eval import time as safe_time

        self.assertFalse(hasattr(safe_time, "sleep"))
        with self.assertRaises(Exception):
            safe_eval("time.sleep(0)", {"time": safe_time})


class TestClosureCacheKey(unittest.TestCase):
    """The validation cache must not let one closure clear another.

    ``lambda: a`` and ``lambda: __class__`` (both closing over an enclosing
    local) compile to *byte-identical* co_code with an empty co_names, differing
    only in co_freevars -- LOAD_DEREF addresses cells by index, not by name.  A
    cache keyed on (co_code, co_names) alone would hand the second expression
    the first's "validated" verdict and skip the dunder check entirely.
    """

    SAFE = "def outer():\n    a = 1\n    return lambda: a\nresult = outer()"
    UNSAFE = "def outer():\n    __class__ = 1\n    return lambda: __class__\nresult = outer()"

    def test_identical_bytecode_differing_freevars(self):
        def inner_code(src):
            outer = compile_codeobj(src, mode="exec")
            fn = next(c for c in outer.co_consts if hasattr(c, "co_consts"))
            return next(c for c in fn.co_consts if hasattr(c, "co_code"))

        safe, unsafe = inner_code(self.SAFE), inner_code(self.UNSAFE)
        self.assertEqual(safe.co_code, unsafe.co_code)
        self.assertEqual(safe.co_names, unsafe.co_names)
        self.assertNotEqual(safe.co_freevars, unsafe.co_freevars)

    def test_safe_closure_does_not_clear_dunder_closure(self):
        safe_eval(self.SAFE, {}, mode="exec")
        with self.assertRaises(NameError):
            safe_eval(self.UNSAFE, {}, mode="exec")


class TestDunderNameCoverage(unittest.TestCase):
    def test_freevars_are_checked(self):
        from odoo.tools.safe_eval import _SAFE_OPCODES, assert_no_dunder_name

        code = compile_codeobj(
            "def outer():\n    __class__ = 1\n    return lambda: __class__", mode="exec"
        )
        fn = next(c for c in code.co_consts if hasattr(c, "co_consts"))
        lam = next(c for c in fn.co_consts if hasattr(c, "co_code"))
        self.assertEqual(lam.co_names, ())
        with self.assertRaises(NameError):
            assert_no_dunder_name(lam, "lambda")
        with self.assertRaises(NameError):
            assert_valid_codeobj(_SAFE_OPCODES, lam, "lambda")


if __name__ == "__main__":
    unittest.main()
