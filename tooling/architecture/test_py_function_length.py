"""The Python function-length budget, and the metric choice behind it."""

import textwrap
import unittest
from pathlib import Path
from unittest import mock

import py_function_length as pfl


def _write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(textwrap.dedent(body))
    return path


class TestMeasure(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _fn(self, lines: int) -> str:
        # `def` + (lines - 1) body lines == `lines` spanned lines.
        return "def f():\n" + "".join(f"    x = {i}\n" for i in range(lines - 1))

    def test_a_function_at_the_budget_is_not_reported(self):
        path = _write(self.tmp, "a.py", self._fn(pfl.MAX_LINES))
        self.assertEqual(pfl.measure([path]), [])

    def test_one_line_over_is_reported(self):
        path = _write(self.tmp, "a.py", self._fn(pfl.MAX_LINES + 1))
        found = pfl.measure([path])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].lines, pfl.MAX_LINES + 1)
        self.assertEqual(found[0].what, "f")

    def test_the_decorator_does_not_count_toward_the_length(self):
        """`node.lineno` is the `def`: a function is not long for being decorated."""
        body = "@deco\n@deco\n@deco\n" + self._fn(pfl.MAX_LINES)
        path = _write(self.tmp, "a.py", body)
        self.assertEqual(pfl.measure([path]), [])

    def test_async_functions_are_measured(self):
        body = "async def f():\n" + "".join(
            f"    x = {i}\n" for i in range(pfl.MAX_LINES)
        )
        path = _write(self.tmp, "a.py", body)
        self.assertEqual(len(pfl.measure([path])), 1)

    def test_nested_functions_are_measured_independently(self):
        outer = (
            "def outer():\n"
            + "".join(f"    x = {i}\n" for i in range(pfl.MAX_LINES))
            + "    def inner():\n"
            + "".join(f"        y = {i}\n" for i in range(pfl.MAX_LINES))
        )
        found = pfl.measure([_write(self.tmp, "a.py", outer)])
        self.assertEqual({f.what for f in found}, {"outer", "inner"})

    def test_a_syntax_error_is_skipped_not_raised(self):
        path = _write(self.tmp, "a.py", "def f(:\n")
        self.assertEqual(pfl.measure([path]), [])

    def test_results_are_longest_first(self):
        path = _write(
            self.tmp,
            "a.py",
            self._fn(pfl.MAX_LINES + 5).replace("def f", "def small")
            + "\n"
            + self._fn(pfl.MAX_LINES + 50).replace("def f", "def big"),
        )
        found = pfl.measure([path])
        self.assertEqual([f.what for f in found], ["big", "small"])


class TestExcessIsTheRatchetedMetric(unittest.TestCase):
    """Why this gate diverges from ``js_function_length``.

    A count-of-offenders ratchet punishes splitting one huge function into
    several merely-long ones, which is the fix the budget exists to encourage.
    Splitting ``_build_cli`` moved the real repo's count 121 -> 127 while excess
    moved 5457 -> 4867. These pin the property that made us choose excess.
    """

    def test_excess_is_the_sum_of_lines_above_budget(self):
        found = [
            pfl.LongFunction("a.py", 1, pfl.MAX_LINES + 10, "a"),
            pfl.LongFunction("b.py", 1, pfl.MAX_LINES + 5, "b"),
        ]
        self.assertEqual(pfl.excess_lines(found), 15)

    def test_splitting_one_long_function_lowers_excess_even_as_count_rises(self):
        before = [pfl.LongFunction("a.py", 1, 1024, "_build_cli")]
        after = [
            pfl.LongFunction("a.py", 1, 294, "_add_database_options"),
            pfl.LongFunction("a.py", 2, 161, "_add_common_options"),
            pfl.LongFunction("a.py", 3, 99, "_build_cli"),
            pfl.LongFunction("a.py", 4, 99, "_add_advanced_options"),
            pfl.LongFunction("a.py", 5, 90, "_add_multiprocessing_options"),
        ]
        self.assertGreater(len(after), len(before), "the count gets worse")
        self.assertLess(
            pfl.excess_lines(after),
            pfl.excess_lines(before),
            "excess must reward the split the count penalises",
        )

    def test_growing_a_function_raises_excess(self):
        smaller = [pfl.LongFunction("a.py", 1, 100, "f")]
        bigger = [pfl.LongFunction("a.py", 1, 120, "f")]
        self.assertEqual(len(smaller), len(bigger), "the count cannot see this")
        self.assertGreater(pfl.excess_lines(bigger), pfl.excess_lines(smaller))


class TestAddonScope(unittest.TestCase):
    """`--addon` selects the tree, the same way `js_function_length.py` does."""

    def test_the_default_addon_is_the_core_package(self):
        self.assertEqual(pfl.addon_src(), pfl.SCOPE)
        self.assertEqual(pfl.addon_src(pfl.DEFAULT_ADDON), pfl.SCOPE)

    def test_the_default_reads_the_module_level_scope(self):
        """So the suite's monkeypatching of `SCOPE` still bites."""
        sentinel = Path("/nowhere/at/all")
        with mock.patch.object(pfl, "SCOPE", sentinel):
            self.assertEqual(pfl.addon_src(), sentinel)

    def test_a_named_addon_resolves_under_addons(self):
        src = pfl.addon_src("stock")
        self.assertEqual(src, pfl.ROOT / "addons" / "stock")
        self.assertNotEqual(src, pfl.SCOPE)

    def test_scanning_an_addon_stays_inside_it_and_skips_tests(self):
        src = pfl.addon_src("stock")
        files = pfl.iter_source_files(src)
        self.assertTrue(files, "the gate scanned nothing under addons/stock")
        self.assertTrue(all(f.is_relative_to(src) for f in files))
        self.assertFalse(
            [f for f in files if "tests" in f.parts or f.name.startswith("test_")]
        )

    def test_an_addon_scan_is_not_the_core_scan(self):
        """A flag that silently measured core would read as a passing floor."""
        self.assertNotEqual(
            pfl.iter_source_files(pfl.addon_src("stock")),
            pfl.iter_source_files(),
        )


class TestRealTree(unittest.TestCase):
    def test_the_scope_is_the_core_package_and_excludes_tests(self):
        files = pfl.iter_source_files()
        self.assertTrue(files, "the gate scanned nothing")
        self.assertTrue(all(f.is_relative_to(pfl.SCOPE) for f in files))
        self.assertFalse(
            [f for f in files if "tests" in f.parts or f.name.startswith("test_")]
        )

    def test_the_gate_refuses_an_empty_tree(self):
        """Measuring nothing must report nothing, not silently pass on garbage."""
        self.assertEqual(pfl.measure([]), [])
        self.assertEqual(pfl.excess_lines([]), 0)

    def test_config_build_cli_is_no_longer_the_outlier(self):
        """Pins the specific defect that motivated the gate."""
        found = pfl.measure()
        by_name = {f.what: f.lines for f in found}
        self.assertNotIn(
            "_build_cli",
            [f.what for f in found if f.lines > 400],
            "_build_cli is over 400 lines again",
        )
        if found:
            self.assertLess(
                found[0].lines, 400, f"a function over 400 lines is back: {found[0]}"
            )
        self.assertLessEqual(by_name.get("_build_cli", 0), 150)


if __name__ == "__main__":
    unittest.main()
