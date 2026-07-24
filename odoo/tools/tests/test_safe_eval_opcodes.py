"""Regression tests for the ``safe_eval`` opcode allowlist on Python 3.14.

The allowlist is a hand-maintained set that every CPython release can silently
narrow. These pin the language constructs server actions / automation rules rely
on so a future interpreter bump fails loudly here instead of in production, and
guard the sandbox invariants (no escape to modules/builtins).
"""

import math
import unittest

from odoo.tools.safe_eval import safe_eval


class TestSafeEvalConstructs(unittest.TestCase):
    """Constructs that must remain executable under the opcode allowlist."""

    def _run(self, src, ctx=None):
        ns = dict(ctx or {})
        safe_eval(src, ns, mode="exec")
        return ns

    def test_try_except_finally(self):
        # emits JUMP_BACKWARD_NO_INTERRUPT on 3.14
        ns = self._run(
            "out = 0\n"
            "try:\n"
            "  out = 1 / divisor\n"
            "except Exception:\n"
            "  out = -1\n"
            "finally:\n"
            "  done = True\n",
            {"divisor": 0, "Exception": Exception},
        )
        self.assertEqual(ns["out"], -1)
        self.assertTrue(ns["done"])

    def test_yield_from(self):
        # needs SEND / END_SEND / CLEANUP_THROW / GET_YIELD_FROM_ITER
        ns = self._run("def gen():\n  yield from [1, 2, 3]\nresult = list(gen())")
        self.assertEqual(ns["result"], [1, 2, 3])

    def test_nested_closure_capturing_local(self):
        # needs MAKE_CELL / LOAD_DEREF / STORE_DEREF / COPY_FREE_VARS
        ns = self._run(
            "def make_adder(n):\n"
            "  def add(x):\n"
            "    return x + n\n"
            "  return add\n"
            "result = make_adder(10)(5)"
        )
        self.assertEqual(ns["result"], 15)

    def test_lambda_capturing_comprehension_var(self):
        ns = self._run("result = [(lambda: x)() for x in [1, 2, 3]]")
        self.assertEqual(ns["result"], [1, 2, 3])


class TestSafeEvalSandbox(unittest.TestCase):
    """The sandbox must keep rejecting escapes and hidden modules."""

    def test_module_hidden_in_dict_key_is_blocked(self):
        with self.assertRaises((TypeError, ValueError)):
            safe_eval("list(d)[0]", {"d": {math: 1}})

    def test_module_hidden_in_dict_value_is_blocked(self):
        with self.assertRaises((TypeError, ValueError)):
            safe_eval("list(d.values())[0]", {"d": {"m": math}})

    def test_dunder_class_escape_blocked(self):
        for expr in ("().__class__", "[].__class__.__bases__", "(1).__class__.__mro__"):
            with self.assertRaises(Exception):
                safe_eval(expr, {})

    def test_str_format_reflection_escape_blocked(self):
        # str.format / str.format_map resolve their field accessors at runtime,
        # so {0.__class__} / {0.__globals__[k]} never reach co_names and slip
        # past the dunder scan. Templates whose fields navigate dunders must be
        # rejected.
        def gadget():
            pass

        escapes = [
            ('"{0.__class__.__mro__}".format(x)', {"x": 1}),
            ('"{0.__globals__}".format(f)', {"f": gadget}),
            ('"{x.__class__}".format_map({"x": 1})', {}),
            # Adjacent literals fold to one constant and must still be caught.
            ('("{0.__cla" "ss__}").format(x)', {"x": 1}),
        ]
        for expr, ns in escapes:
            with self.assertRaises(Exception):
                safe_eval(expr, ns)

    def test_str_format_legitimate_uses_allowed(self):
        # The fix must be surgical: ordinary str.format and model methods also
        # named ``format`` (e.g. currency.format(amount)) must keep working.
        self.assertEqual(safe_eval('"{0.real}".format(x)', {"x": 5}), "5")
        self.assertEqual(safe_eval('"hello {}".format(n)', {"n": "world"}), "hello world")
        self.assertEqual(safe_eval('"{a}-{b}".format(a=1, b=2)', {}), "1-2")

        class FakeCurrency:
            def format(self, amount):
                return f"${amount}"

        self.assertEqual(safe_eval("c.format(v)", {"c": FakeCurrency(), "v": 9}), "$9")
        # f-strings remain fully supported.
        self.assertEqual(safe_eval('f"{a}-{b}"', {"a": 1, "b": 2}), "1-2")

    def test_time_sleep_not_exposed(self):
        # time.sleep would let a single expression block a worker thread (DoS).
        from odoo.tools.safe_eval import time as safe_time

        self.assertFalse(hasattr(safe_time, "sleep"))
        with self.assertRaises(Exception):
            safe_eval("time.sleep(0)", {"time": safe_time})


if __name__ == "__main__":
    unittest.main()
