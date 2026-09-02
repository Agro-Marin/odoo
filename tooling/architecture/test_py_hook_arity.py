import tempfile
import textwrap
import unittest
from pathlib import Path

import _ast_cache
import py_hook_arity as pha


class TestMeasure(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _measure(self, body: str):
        path = self.tmp / "a.py"
        path.write_text(textwrap.dedent(body))
        return pha.measure([path])

    def test_a_hook_taking_only_self_is_clean(self):
        self.assertEqual(
            self._measure(
                """
                @api.depends("x")
                def _compute_y(self):
                    pass
                """
            ),
            [],
        )

    def test_a_surplus_parameter_without_a_default_is_fatal(self):
        found = self._measure(
            """
            @api.depends("x")
            def _get_helper(self, invoice, sign):
                pass
            """
        )
        self.assertEqual(
            [(f.method, f.extra, f.fatal) for f in found],
            [("_get_helper", "invoice, sign", True)],
        )

    def test_a_surplus_parameter_with_a_default_is_masked_not_fatal(self):
        found = self._measure(
            """
            @api.constrains("x")
            def _check_thing(self, on_unlink=False):
                pass
            """
        )
        self.assertEqual([(f.extra, f.fatal) for f in found], [("on_unlink", False)])

    def test_a_partial_default_is_still_fatal(self):
        found = self._measure(
            """
            @api.depends("x")
            def _compute_y(self, a, b=1):
                pass
            """
        )
        self.assertEqual([(f.extra, f.fatal) for f in found], [("a, b", True)])

    def test_varargs_and_kwargs_are_reported_but_masked(self):
        found = self._measure(
            """
            @api.onchange("x")
            def _onchange_x(self, *args, **kwargs):
                pass
            """
        )
        self.assertEqual(
            [(f.extra, f.fatal) for f in found], [("*args, **kwargs", False)]
        )

    def test_a_keyword_only_parameter_counts(self):
        found = self._measure(
            """
            @api.depends("x")
            def _compute_y(self, *, mode):
                pass
            """
        )
        self.assertEqual([(f.extra, f.fatal) for f in found], [("mode", True)])

    def test_every_no_argument_hook_is_covered(self):
        for hook in sorted(pha.NO_ARGUMENT_HOOKS):
            with self.subTest(hook=hook):
                found = self._measure(
                    f"""
                    @api.{hook}("x")
                    def _f(self, surplus):
                        pass
                    """
                )
                self.assertEqual([f.hook for f in found], [hook])

    def test_decorators_that_only_describe_the_call_are_out_of_scope(self):
        for decorator in ("api.model", "api.model_create_multi", "api.autovacuum"):
            with self.subTest(decorator=decorator):
                self.assertEqual(
                    self._measure(
                        f"""
                        @{decorator}
                        def _f(self, vals_list):
                            pass
                        """
                    ),
                    [],
                )

    def test_a_bare_decorator_without_a_call_is_seen(self):
        found = self._measure(
            """
            @api.ondelete
            def _f(self, surplus):
                pass
            """
        )
        self.assertEqual(len(found), 1)

    def test_stacked_hooks_are_reported_once_naming_both(self):
        found = self._measure(
            """
            @api.depends("x")
            @api.depends_context("uid")
            def _f(self, surplus):
                pass
            """
        )
        self.assertEqual([f.hook for f in found], ["depends/depends_context"])

    def test_an_unparseable_file_is_reported_not_skipped(self):
        path = self.tmp / "broken.py"
        path.write_text("def (:\n")
        with self.assertRaises(_ast_cache.SourceUnreadable) as caught:
            pha.measure([path])
        self.assertIn(str(path), str(caught.exception))


class TestScopes(unittest.TestCase):
    def test_an_empty_tree_is_refused_rather_than_reported_clean(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(RuntimeError):
                pha.measure(src=Path(empty))

    def test_every_governed_scope_resolves_to_a_path(self):
        for addon in pha.GOVERNED_ADDONS:
            with self.subTest(addon=addon):
                self.assertIsInstance(pha.addon_src(addon), Path)


if __name__ == "__main__":
    unittest.main()
