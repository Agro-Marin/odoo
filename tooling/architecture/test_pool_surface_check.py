import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pool_surface_check as psc


def _check_source(source: str, layer: str = "Layer 1", name: str = "probe.py"):
    tmp = Path(psc.REPO_ROOT) / "odoo" / "orm" / "fields" / f"__selftest_{name}"
    report = psc.Report(registry_members=psc.registry_members())
    collector = psc._PoolReachCollector()
    collector.visit(ast.parse(source))
    rel = tmp.relative_to(psc.REPO_ROOT).as_posix()
    for attr, lineno, subscript in collector.hits:
        reach = psc.Reach(rel, layer, attr, lineno, subscript)
        report.reaches.append(reach)
        if layer == "components":
            report.component_reaches.append(reach)
            continue
        if attr not in report.registry_members and not attr.startswith("__"):
            report.unknown_members.append(reach)
        if reach.is_private:
            (report.known if psc._is_known(rel, attr) else report.new).append(reach)
    return report


class TestCollector(unittest.TestCase):
    def test_attribute_reach_is_collected(self):
        report = _check_source("def f(m):\n    return m.pool.field_inverses\n")
        self.assertEqual([r.attr for r in report.reaches], ["field_inverses"])

    def test_bare_pool_name_is_collected(self):
        report = _check_source("def f(pool):\n    return pool.ready\n")
        self.assertEqual([r.attr for r in report.reaches], ["ready"])

    def test_subscript_is_recorded_as_getitem_not_as_a_private_reach(self):
        report = _check_source('def f(m):\n    return m.pool["res.partner"]\n')
        self.assertEqual([r.attr for r in report.reaches], ["__getitem__"])
        self.assertTrue(report.reaches[0].subscript)
        self.assertFalse(report.reaches[0].is_private)
        self.assertEqual(report.new, [])

    def test_unrelated_attribute_named_pool_on_nothing_is_not_matched(self):
        report = _check_source("def f(m):\n    return m.poolish.ready\n")
        self.assertEqual(report.reaches, [])


class TestEnforcement(unittest.TestCase):
    def test_new_private_reach_fails(self):
        report = _check_source("def f(m):\n    return m.pool._foreign_keys\n")
        self.assertFalse(report.ok)
        self.assertEqual([r.attr for r in report.new], ["_foreign_keys"])

    def test_nonexistent_member_fails(self):
        report = _check_source("def f(m):\n    return m.pool.no_such_member\n")
        self.assertFalse(report.ok)
        self.assertEqual([r.attr for r in report.unknown_members], ["no_such_member"])

    def test_components_may_not_touch_pool_at_all(self):
        report = _check_source(
            "def f(m):\n    return m.pool.ready\n", layer="components"
        )
        self.assertFalse(report.ok)
        self.assertEqual([r.attr for r in report.component_reaches], ["ready"])

    def test_public_member_is_reported_not_failed(self):
        report = _check_source("def f(m):\n    return m.pool.field_computed\n")
        self.assertTrue(report.ok)
        self.assertEqual(len(report.reaches), 1)


class TestRegistryMembers(unittest.TestCase):
    def test_imperatively_created_members_are_found(self):
        members = psc.registry_members()
        for name in ("_init_phase", "_ordinary_tables", "many2many_relations"):
            self.assertIn(name, members, f"{name} not discovered on Registry")

    def test_mapping_interface_is_included(self):
        members = psc.registry_members()
        self.assertIn("get", members)
        self.assertIn("keys", members)

    def test_class_body_members_are_found(self):
        members = psc.registry_members()
        for name in ("ready", "post_init", "add_foreign_key", "get_trigger_tree"):
            self.assertIn(name, members)


class TestRegistrySurfaceIsNotOverCollected(unittest.TestCase):
    FOREIGN = ("acquire", "release", "clear_group", "clear_all", "lrus", "by_db")

    def test_neighbouring_helper_class_members_are_not_registry_members(self):
        members = psc.registry_members()
        leaked = [name for name in self.FOREIGN if name in members]
        self.assertEqual(
            leaked,
            [],
            f"{leaked} are not on Registry; they leaked in from a helper class "
            f"in REGISTRY_SOURCES. Check REGISTRY_CLASSES.",
        )

    def test_a_reach_to_a_foreign_helper_member_is_reported(self):
        report = _check_source("def f(m):\n    return m.pool.acquire\n")
        self.assertFalse(report.ok)
        self.assertEqual([r.attr for r in report.unknown_members], ["acquire"])

    def test_registry_classes_all_exist_in_the_sources(self):
        found = set()
        for path in psc.REGISTRY_SOURCES:
            if not path.is_file():
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ClassDef):
                    found.add(node.name)
        self.assertEqual(
            psc.REGISTRY_CLASSES - found,
            set(),
            "REGISTRY_CLASSES names a class that no longer exists",
        )


class TestScopeCompleteness(unittest.TestCase):
    def test_every_orm_module_is_scoped_or_exempt(self):
        import _orm_layer_scope as scope

        missing = scope.unclassified_modules(psc.CORE)
        self.assertEqual(
            missing,
            [],
            f"ORM module(s) in neither SCOPE nor EXEMPT nor orm/runtime: "
            f"{missing} — give each a layer in _orm_layer_scope.SCOPE, or an "
            f"argued entry in _orm_layer_scope.EXEMPT",
        )

    def test_the_two_seam_gates_share_one_scope(self):
        import env_surface_check as esc

        self.assertIs(psc.SCOPE, esc.SCOPE)

    def test_registration_is_actually_scanned(self):
        scanned = {
            p.relative_to(psc.CORE).as_posix() for p, _ in psc.iter_scope_files()
        }
        self.assertIn("orm/registration.py", scanned)
        self.assertIn("orm/helpers.py", scanned)

    def test_exempt_entries_name_real_files(self):
        import _orm_layer_scope as scope

        for rel in scope.EXEMPT:
            self.assertTrue(
                (psc.CORE / rel).is_file(), f"EXEMPT names a missing file: {rel}"
            )


class TestNotVacuous(unittest.TestCase):
    def test_the_real_scan_actually_finds_something(self):
        report = psc.check()
        self.assertGreater(
            len(report.reaches), 30, "the pool surface scan found almost nothing"
        )
        layers = {r.layer for r in report.reaches}
        self.assertIn("Layer 1", layers)
        self.assertIn("Layer 2", layers)

    def test_repository_is_currently_clean(self):
        report = psc.check()
        self.assertTrue(
            report.ok,
            f"new={[(r.path, r.attr) for r in report.new]} "
            f"unknown={[(r.path, r.attr) for r in report.unknown_members]} "
            f"components={[(r.path, r.attr) for r in report.component_reaches]}",
        )

    def test_every_pinned_violation_still_exists(self):
        report = psc.check()
        pinned = {(k.path, k.attr) for k in psc.KNOWN_VIOLATIONS}
        found = {(r.path, r.attr) for r in report.known}
        self.assertEqual(
            pinned,
            found,
            "KNOWN_VIOLATIONS no longer matches reality; remove the fixed entry",
        )


if __name__ == "__main__":
    unittest.main()
