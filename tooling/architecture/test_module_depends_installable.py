from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import _ast_cache
import module_depends_installable as gate


def write_module(
    root: Path,
    name: str,
    *,
    depends: list[str] | None = None,
    installable: bool | None = None,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"name": name, "depends": depends or []}
    if installable is not None:
        manifest["installable"] = installable
    (directory / "__manifest__.py").write_text(repr(manifest), encoding="utf-8")
    return directory


class MeasureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "addons"
        self.root.mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def measure(self):
        return gate.measure([self.root])

    def test_a_clean_tree_reports_nothing(self):
        write_module(self.root, "base_thing")
        write_module(self.root, "user", depends=["base_thing"])

        self.assertEqual(self.measure(), [])

    def test_it_finds_a_dependency_marked_uninstallable(self):
        write_module(self.root, "disabled", installable=False)
        write_module(self.root, "user", depends=["disabled"])

        found = self.measure()

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].module, "user")
        self.assertEqual(found[0].dependency, "disabled")

    def test_an_uninstallable_module_may_depend_on_an_uninstallable_one(self):
        write_module(self.root, "disabled", installable=False)
        write_module(
            self.root, "also_disabled", depends=["disabled"], installable=False
        )

        self.assertEqual(self.measure(), [])

    def test_a_dependency_absent_from_scope_is_not_an_offence(self):
        write_module(self.root, "user", depends=["lives_in_another_checkout"])

        self.assertEqual(self.measure(), [])

    def test_installable_defaults_to_true_when_the_key_is_absent(self):
        write_module(self.root, "disabled", installable=False)
        write_module(self.root, "user", depends=["disabled"])

        self.assertEqual(len(self.measure()), 1)

    def test_every_dependent_is_reported_not_just_the_first(self):
        write_module(self.root, "disabled", installable=False)
        for name in ("one", "two", "three"):
            write_module(self.root, name, depends=["disabled"])

        self.assertEqual({o.module for o in self.measure()}, {"one", "two", "three"})

    def test_a_module_reports_once_per_bad_dependency(self):
        write_module(self.root, "a", installable=False)
        write_module(self.root, "b", installable=False)
        write_module(self.root, "user", depends=["a", "b"])

        self.assertEqual({o.dependency for o in self.measure()}, {"a", "b"})

    def test_an_unparseable_manifest_is_reported_rather_than_skipped(self):
        write_module(self.root, "fine")
        broken = self.root / "broken"
        broken.mkdir()
        manifest = broken / "__manifest__.py"
        manifest.write_text("{ this is not python", encoding="utf-8")

        with self.assertRaises(_ast_cache.SourceUnreadable) as caught:
            self.measure()
        self.assertIn(str(manifest), str(caught.exception))

    def test_it_refuses_a_tree_with_no_manifests(self):
        with self.assertRaises(RuntimeError) as caught:
            self.measure()

        self.assertIn("measured over nothing", str(caught.exception))

    def test_it_refuses_a_root_that_does_not_exist(self):
        with self.assertRaises(RuntimeError) as caught:
            gate.measure([self.root / "nope"])

        self.assertIn("no such directory", str(caught.exception))


class AbsenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "addons"
        self.root.mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def measure(self):
        return gate.measure_absent([self.root])

    def test_a_dependency_every_root_supplies_is_not_an_absence(self):
        write_module(self.root, "supplier")
        write_module(self.root, "user", depends=["supplier"])

        self.assertEqual(self.measure(), [])

    def test_it_finds_a_dependency_no_root_supplies(self):
        write_module(self.root, "user", depends=["lives_in_another_checkout"])

        found = self.measure()

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].module, "user")
        self.assertEqual(found[0].dependency, "lives_in_another_checkout")

    def test_an_uninstallable_module_may_name_an_absent_dependency(self):
        write_module(self.root, "user", depends=["gone"], installable=False)

        self.assertEqual(self.measure(), [])

    def test_a_second_root_supplies_what_the_first_lacks(self):
        other = self.root.parent / "enterprise"
        other.mkdir()
        write_module(self.root, "user", depends=["over_there"])
        write_module(other, "over_there")

        self.assertEqual(gate.measure_absent([self.root, other]), [])

    def test_removing_that_root_is_what_the_mode_reports(self):
        write_module(self.root, "user", depends=["over_there"])

        self.assertEqual(len(self.measure()), 1)


class ExitCodeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "addons"
        self.root.mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def test_check_exits_zero_on_a_clean_tree(self):
        write_module(self.root, "fine")

        self.assertEqual(gate.main(["--check", "--roots", str(self.root)]), 0)

    def test_check_exits_one_when_a_module_is_unreachable(self):
        write_module(self.root, "disabled", installable=False)
        write_module(self.root, "user", depends=["disabled"])

        self.assertEqual(gate.main(["--check", "--roots", str(self.root)]), 1)

    def test_it_exits_two_rather_than_reporting_a_clean_zero_over_nothing(self):
        self.assertEqual(gate.main(["--check", "--roots", str(self.root)]), 2)

    def test_an_absent_dependency_passes_while_the_mode_is_off(self):
        write_module(self.root, "user", depends=["gone"])

        self.assertEqual(gate.main(["--check", "--roots", str(self.root)]), 0)

    def test_an_absent_dependency_fails_once_the_mode_is_on(self):
        write_module(self.root, "user", depends=["gone"])

        self.assertEqual(
            gate.main(["--check", "--require-present", "--roots", str(self.root)]),
            1,
        )

    def _count(self, *extra: str) -> str:
        stream = io.StringIO()
        with redirect_stdout(stream):
            gate.main(["--count", "--roots", str(self.root), *extra])
        return stream.getvalue().strip()

    def test_the_count_sums_both_questions(self):
        write_module(self.root, "disabled", installable=False)
        write_module(self.root, "user", depends=["disabled", "gone"])

        self.assertEqual(self._count(), "1")
        self.assertEqual(self._count("--require-present"), "2")


if __name__ == "__main__":
    unittest.main()
