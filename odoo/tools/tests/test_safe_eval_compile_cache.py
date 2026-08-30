import typing
import unittest

from odoo.tools import safe_eval as se
from odoo.tools.safe_eval import safe_eval


class TestTheCacheIsInvisible(unittest.TestCase):
    def _twice(self, expr, context=None, **kw):
        first = dict(context or {})
        second = dict(context or {})
        a: tuple[typing.Any, typing.Any]
        b: tuple[typing.Any, typing.Any]
        try:
            a = (safe_eval(expr, first, **kw), None)
        except Exception as exc:
            a = (None, (type(exc), str(exc)))
        try:
            b = (safe_eval(expr, second, **kw), None)
        except Exception as exc:
            b = (None, (type(exc), str(exc)))
        self.assertEqual(a, b, f"warm call diverged for {expr!r}")
        self.assertEqual(first, second, f"context diverged for {expr!r}")
        return a

    def test_values_are_stable_across_calls(self):
        for expr, ctx in (
            ("1 + 1", {}),
            ("  [1, 2, 3]  ", {}),
            ("[i * 2 for i in r]", {"r": [1, 2, 3]}),
            ("sorted([3, 1, 2], key=lambda z: -z)", {}),
        ):
            with self.subTest(expr=expr):
                self._twice(expr, ctx)

    def test_the_sandbox_still_refuses_the_same_things(self):
        for expr in ("__import__('os')", "a.__class__", "'{0.__class__}'.format(v)"):
            with self.subTest(expr=expr):
                value, error = self._twice(expr, {"a": 1, "v": 7})
                self.assertIsNone(value)
                self.assertIs(error[0], NameError)

    def test_exec_mode_still_writes_back_into_the_context(self):
        context = {"x": 21}
        safe_eval("result = x * 2", context, mode="exec")
        self.assertEqual(context["result"], 42)
        context2 = {"x": 21}
        safe_eval("result = x * 2", context2, mode="exec")
        self.assertEqual(context2["result"], 42)

    def test_bytes_and_bytearray_are_accepted(self):
        self.assertEqual(safe_eval(b"{'a': 1}"), {"a": 1})
        self.assertEqual(safe_eval(bytearray(b"'x' * 3")), "xxx")  # type: ignore[arg-type]

    def test_a_code_object_is_still_refused(self):
        with self.assertRaises(TypeError):
            safe_eval(compile("1", "<t>", "eval"))

    def test_a_syntax_error_is_not_cached_as_a_success(self):
        for _ in range(2):
            with self.assertRaises(SyntaxError):
                safe_eval("(")


class TestTheCacheKeySeparatesWhatMatters(unittest.TestCase):
    def test_mode_is_part_of_the_key(self):
        self.assertIsNone(safe_eval("x = 1", {}, mode="exec"))
        with self.assertRaises(SyntaxError):
            safe_eval("x = 1", {}, mode="eval")

    def test_filename_is_part_of_the_key(self):
        a = se._compile_and_validate("1", "<a>", "eval")
        b = se._compile_and_validate("1", "<b>", "eval")
        self.assertEqual(a.co_filename, "<a>")
        self.assertEqual(b.co_filename, "<b>")

    def test_the_same_call_returns_the_same_object(self):
        a = se._compile_and_validate("1 + 1", "<t>", "eval")
        b = se._compile_and_validate("1 + 1", "<t>", "eval")
        self.assertIs(a, b, "the second call recompiled")

    def test_the_cache_is_bounded(self):
        self.assertEqual(
            se._compile_and_validate.cache_info().maxsize,
            se._VALIDATED_CACHE_MAX,
            "an unbounded cache would grow with runtime-built expressions",
        )

    def test_the_shared_builtins_carry_the_format_guard(self):
        self.assertIs(se._SAFE_BUILTINS[se._GUARD_FORMAT_NAME], se._guard_format)
        self.assertEqual(
            {k: v for k, v in se._SAFE_BUILTINS.items() if k != se._GUARD_FORMAT_NAME},
            se._BUILTINS,
        )


if __name__ == "__main__":
    unittest.main()
