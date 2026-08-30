from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import module_suite_lane as gate


def write_module(
    root: Path,
    name: str,
    *,
    tests: int = 0,
    installable: bool | None = None,
) -> Path:
    directory = root / name
    (directory / "tests").mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"name": name}
    if installable is not None:
        manifest["installable"] = installable
    (directory / "__manifest__.py").write_text(repr(manifest), encoding="utf-8")
    if tests:
        body = "\n".join(
            f"    def test_{i}(self):\n        pass\n" for i in range(tests)
        )
        (directory / "tests" / "test_it.py").write_text(
            f"class T:\n{body}", encoding="utf-8"
        )
    return directory


def write_lane(workflows: Path, name: str, tags: str, *, enable: bool = True) -> None:
    workflows.mkdir(parents=True, exist_ok=True)
    enabled = "--test-enable" if enable else ""
    (workflows / f"{name}.yml").write_text(
        f"jobs:\n  x:\n    steps:\n      - run: |\n"
        f"          odoo-bin {enabled} --test-tags '{tags}'\n",
        encoding="utf-8",
    )


class MeasureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "addons"
        self.root.mkdir(parents=True)
        self.workflows = base / "workflows"
        self.addCleanup(self._tmp.cleanup)

    def measure(self):
        return gate.measure([self.root], self.workflows)

    def test_a_module_a_lane_names_is_not_an_offence(self):
        write_module(self.root, "thing", tests=3)
        write_lane(self.workflows, "ci", "/thing")

        self.assertEqual(self.measure(), [])

    def test_a_module_no_lane_names_is_reported_with_its_size(self):
        write_module(self.root, "thing", tests=3)
        write_module(self.root, "other", tests=1)
        write_lane(self.workflows, "ci", "/other")

        found = self.measure()

        self.assertEqual([o.module for o in found], ["thing"])
        self.assertEqual(found[0].tests, 3)

    def test_a_module_with_no_tests_is_not_asked_to_have_a_lane(self):
        write_module(self.root, "thing", tests=0)
        write_module(self.root, "other", tests=1)
        write_lane(self.workflows, "ci", "/other")

        self.assertEqual(self.measure(), [])

    def test_being_installed_is_not_being_run(self):
        # The distinction the gate exists on: `sale` is installed by the
        # base_order lane so that suite's registry holds what its tests reach
        # for, and `sale`'s own tests do not run there.
        write_module(self.root, "sale", tests=5)
        write_module(self.root, "test_base_order", tests=2)
        (self.workflows).mkdir(parents=True, exist_ok=True)
        (self.workflows / "ci.yml").write_text(
            "jobs:\n  x:\n    steps:\n      - run: |\n"
            "          odoo-bin -i test_base_order,sale --test-enable "
            "--test-tags '/test_base_order'\n",
            encoding="utf-8",
        )

        self.assertEqual([o.module for o in self.measure()], ["sale"])

    def test_a_lane_that_enables_no_tests_covers_nothing(self):
        write_module(self.root, "thing", tests=2)
        write_module(self.root, "other", tests=1)
        write_lane(self.workflows, "installability", "/thing", enable=False)
        write_lane(self.workflows, "ci", "/other")

        self.assertEqual([o.module for o in self.measure()], ["thing"])

    def test_a_negated_tag_does_not_cover_the_module_it_excludes(self):
        write_module(self.root, "thing", tests=2)
        write_module(self.root, "other", tests=1)
        write_lane(self.workflows, "ci", "/other,-/thing")

        self.assertEqual([o.module for o in self.measure()], ["thing"])

    def test_a_tag_naming_one_class_still_covers_the_module(self):
        write_module(self.root, "thing", tests=2)
        write_lane(self.workflows, "ci", "/thing:TestOne.test_a")

        self.assertEqual(self.measure(), [])

    def test_an_uninstallable_module_is_not_asked_for_a_lane(self):
        write_module(self.root, "retired", tests=9, installable=False)
        write_module(self.root, "other", tests=1)
        write_lane(self.workflows, "ci", "/other")

        self.assertEqual(self.measure(), [])

    def test_an_exempt_module_reports_its_decision_rather_than_an_offence(self):
        write_module(self.root, next(iter(gate.EXEMPT)), tests=200)
        write_module(self.root, "other", tests=1)
        write_lane(self.workflows, "ci", "/other")

        self.assertEqual(self.measure(), [])

    def test_the_biggest_silence_is_reported_first(self):
        write_module(self.root, "small", tests=1)
        write_module(self.root, "big", tests=50)
        write_module(self.root, "seen", tests=1)
        write_lane(self.workflows, "ci", "/seen")

        self.assertEqual([o.module for o in self.measure()], ["big", "small"])


class RefusalTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self.base / "addons"
        self.root.mkdir(parents=True)
        self.workflows = self.base / "workflows"
        self.addCleanup(self._tmp.cleanup)

    def test_a_tree_with_no_tested_module_is_refused(self):
        write_lane(self.workflows, "ci", "/thing")

        with self.assertRaises(RuntimeError):
            gate.measure([self.root], self.workflows)

    def test_a_workflow_directory_naming_no_module_is_refused(self):
        # Otherwise every module reports as uncovered, which is a full-tree
        # offence list produced by a broken scan rather than by a finding.
        write_module(self.root, "thing", tests=2)
        write_lane(self.workflows, "ci", "-:SomeClass")

        with self.assertRaises(RuntimeError):
            gate.measure([self.root], self.workflows)

    def test_a_missing_root_is_refused(self):
        write_lane(self.workflows, "ci", "/thing")

        with self.assertRaises(RuntimeError):
            gate.measure([self.base / "nope"], self.workflows)

    def test_a_missing_workflow_directory_is_refused(self):
        write_module(self.root, "thing", tests=2)

        with self.assertRaises(RuntimeError):
            gate.measure([self.root], self.base / "nope")


if __name__ == "__main__":
    unittest.main()
