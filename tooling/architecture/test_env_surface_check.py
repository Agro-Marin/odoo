#!/usr/bin/env python3


from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import env_surface_check as esc


def _check_source(src: str, layer: str = "Layer 1", name: str = "probe.py"):
    tmp = Path(esc.REPO_ROOT) / "odoo" / "orm" / "fields" / f"_{name}"
    tmp.write_text(src, encoding="utf-8")
    try:
        return esc.check(files=[(tmp, layer)])
    finally:
        tmp.unlink()


class TestCollectorFindsReaches(unittest.TestCase):
    def test_self_env_private_is_a_new_violation(self):
        report = _check_source("def f(self):\n    return self.env._secret_thing\n")
        self.assertEqual([r.attr for r in report.new], ["_secret_thing"])

    def test_bare_env_private_is_a_new_violation(self):
        report = _check_source("def f(env):\n    return env._secret_thing\n")
        self.assertEqual([r.attr for r in report.new], ["_secret_thing"])

    def test_public_member_is_not_a_violation(self):
        report = _check_source("def f(self):\n    return self.env.context\n")
        self.assertEqual(report.new, [])
        self.assertTrue(report.ok)

    def test_sanctioned_private_members_pass(self):
        for attr in sorted(esc.SANCTIONED_PRIVATE):
            with self.subTest(attr=attr):
                report = _check_source(f"def f(self):\n    return self.env.{attr}\n")
                self.assertEqual(report.new, [], f"env.{attr} should be sanctioned")

    def test_components_may_reach_env_for_nothing(self):
        report = _check_source(
            "def f(self):\n    return self.env.context\n", layer="components"
        )
        self.assertEqual([r.attr for r in report.new], ["context"])


class TestCatchesRename(unittest.TestCase):
    def test_dict_key_is_resolved_to_the_member_it_names(self):
        report = _check_source(
            'def f(env):\n    return env.__dict__["_field_cache_memo"]\n'
        )
        attrs = [r.attr for r in report.reaches]
        self.assertIn("_field_cache_memo", attrs)
        self.assertNotIn("__dict__", attrs, "must not double-count the bare __dict__")
        self.assertTrue(any(r.via_dict for r in report.reaches))

    def test_nonexistent_member_via_dict_key_is_flagged(self):
        report = _check_source(
            'def f(env):\n    return env.__dict__["_renamed_away"]\n'
        )
        self.assertEqual([r.attr for r in report.unknown_members], ["_renamed_away"])
        self.assertFalse(report.ok)

    def test_nonexistent_plain_attribute_is_flagged(self):
        report = _check_source("def f(self):\n    return self.env.no_such_member\n")
        self.assertEqual([r.attr for r in report.unknown_members], ["no_such_member"])
        self.assertFalse(report.ok)


class TestEnvironmentMembers(unittest.TestCase):
    def test_inherited_mapping_methods_are_resolved(self):
        self.assertIn("get", esc.environment_members())

    def test_class_body_members_are_resolved(self):
        members = esc.environment_members()
        for name in ("cr", "uid", "context", "su", "registry", "_core"):
            with self.subTest(name=name):
                self.assertIn(name, members)

    def test_agrees_with_the_runtime_class(self):
        if str(esc.REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(esc.REPO_ROOT))
        try:
            from odoo.orm.runtime.environment import Environment
        except Exception as exc:  # pragma: no cover - env-dependent
            raise unittest.SkipTest(f"odoo not importable: {exc}") from exc
        parsed = esc.environment_members()
        runtime = set(dir(Environment))
        missed = {n for n in runtime if not n.startswith("__") and n not in parsed}
        self.assertEqual(
            missed,
            set(),
            f"AST parse missed real Environment members: {sorted(missed)}",
        )


class TestPinsAreLive(unittest.TestCase):
    def test_every_known_violation_still_exists(self):
        report = esc.check()
        pinned = {(k.path, k.attr) for k in esc.KNOWN_VIOLATIONS}
        seen = {(r.path, r.attr) for r in report.known}
        self.assertEqual(
            pinned - seen,
            set(),
            "KNOWN_VIOLATIONS entries that no longer match any source line — "
            "remove them (the debt was paid) rather than leaving them to rot",
        )

    def test_known_violation_files_exist(self):
        for k in esc.KNOWN_VIOLATIONS:
            with self.subTest(path=k.path):
                self.assertTrue((esc.REPO_ROOT / k.path).is_file(), k.path)

    def test_every_pin_states_a_reason(self):
        for k in esc.KNOWN_VIOLATIONS:
            with self.subTest(path=k.path, attr=k.attr):
                self.assertGreater(len(k.reason.strip()), 40)


class TestRealTree(unittest.TestCase):
    def test_the_tree_is_currently_clean(self):
        report = esc.check()
        self.assertEqual(
            [(r.path, r.lineno, r.attr) for r in report.new],
            [],
            "new unsanctioned env reach — pin it or route it through a public accessor",
        )
        self.assertEqual(
            [(r.path, r.lineno, r.attr) for r in report.unknown_members],
            [],
            "a reached Environment member does not exist",
        )

    def test_components_reaches_env_for_nothing(self):
        report = esc.check()
        self.assertEqual(
            [r for r in report.reaches if r.layer == "components"],
            [],
            "orm/components must be usable without an Environment",
        )

    def test_scope_paths_all_exist(self):
        for rel in esc.SCOPE:
            with self.subTest(rel=rel):
                self.assertTrue(
                    (esc.CORE / rel).exists(), f"SCOPE names a missing path: {rel}"
                )

    def test_the_widened_scope_is_actually_scanned(self):

        scanned = {
            p.relative_to(esc.CORE).as_posix() for p, _ in esc.iter_scope_files()
        }
        for rel in (
            "orm/registration.py",
            "orm/helpers.py",
            "orm/_recordset.py",
            "orm/decorators.py",
            "orm/constants.py",
            "orm/_typing.py",
        ):
            with self.subTest(rel=rel):
                self.assertIn(rel, scanned)

    def test_environment_declares_all_its_members_in_the_class_body(self):

        tree = ast.parse(esc.ENVIRONMENT_PY.read_text(encoding="utf-8"))
        declared, imperative = set(), set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef) and node.name == "Environment"):
                continue
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    declared.add(stmt.name)
                elif isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    declared.add(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    declared.update(
                        t.id for t in stmt.targets if isinstance(t, ast.Name)
                    )
            for sub in ast.walk(node):
                targets = (
                    list(sub.targets)
                    if isinstance(sub, ast.Assign)
                    else [sub.target]
                    if isinstance(sub, ast.AnnAssign)
                    else []
                )
                imperative.update(
                    t.attr
                    for t in targets
                    if isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == "self"
                )
        undeclared = sorted(imperative - declared)
        self.assertEqual(
            undeclared,
            [],
            f"Environment now creates {undeclared} imperatively. "
            f"environment_members() reads the class body only and will report "
            f"every reach to them as 'does not exist' — teach it to walk "
            f"self.<name> assignments, as registry_members() does.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
