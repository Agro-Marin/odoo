#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import external_dependency_pins as edp


class Tree:
    """A checkout shaped like the real one: a core repo with two requirements
    files, and a sibling repo with one."""

    def __init__(self, stack: TemporaryDirectory):
        self.root = Path(stack.name)
        self.core = self.root / "core"
        self.sibling = self.root / "sibling"
        (self.core / "addons").mkdir(parents=True)
        self.sibling.mkdir()
        self.requirements(core="", addons="")

    def requirements(self, *, core=None, addons=None, sibling=None):
        if core is not None:
            (self.core / "requirements.txt").write_text(core)
        if addons is not None:
            (self.core / "requirements-addons.txt").write_text(addons)
        if sibling is not None:
            (self.sibling / "requirements.txt").write_text(sibling)

    def module(self, tree: Path, name: str, deps: list[str] | None = None):
        path = tree / name
        path.mkdir(parents=True, exist_ok=True)
        external = f', "external_dependencies": {{"python": {deps!r}}}' if deps else ""
        (path / "__manifest__.py").write_text('{"name": "%s"%s}' % (name, external))
        return path


class PinCase(unittest.TestCase):
    def setUp(self):
        self._stack = TemporaryDirectory()
        self.addCleanup(self._stack.cleanup)
        self.tree = Tree(self._stack)
        self._root = edp.ROOT
        edp.ROOT = self.tree.core
        self.addCleanup(setattr, edp, "ROOT", self._root)

    def measure(self, *trees):
        return edp.measure(list(trees) or [self.tree.core / "addons"])


class ADeclaredDependencyMustBePinned(PinCase):
    def test_a_pinned_dependency_is_not_a_finding(self):
        self.tree.requirements(addons="requests==2.34.2\n")
        self.tree.module(self.tree.core / "addons", "mod", ["requests"])

        self.assertEqual(self.measure(), [])

    def test_an_unpinned_dependency_is_a_finding(self):
        self.tree.requirements(addons="requests==2.34.2\n")
        self.tree.module(self.tree.core / "addons", "mod", ["phonenumbers"])

        findings = self.measure()

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].dependency, "phonenumbers")
        self.assertEqual(findings[0].module, "mod")

    def test_a_module_declaring_nothing_is_never_a_finding(self):
        self.tree.requirements(addons="requests==2.34.2\n")
        self.tree.module(self.tree.core / "addons", "quiet")
        self.tree.module(self.tree.core / "addons", "loud", ["requests"])

        self.assertEqual(self.measure(), [])

    def test_a_pin_that_no_module_declares_is_not_a_finding(self):
        """The reverse direction is deliberately uncounted: guidelines 1.2 asks
        modules to declare only what they cannot start without, so an optional
        dependency is pinned and undeclared by design."""
        self.tree.requirements(addons="requests==2.34.2\nxlrd==2.0.2\nodfpy==1.4.1\n")
        self.tree.module(self.tree.core / "addons", "mod", ["requests"])

        self.assertEqual(self.measure(), [])


class NamesAreComparedTheWayPipCompares(PinCase):
    def test_underscores_and_dots_and_case_all_normalise(self):
        self.tree.requirements(addons="pdfminer.six==20260107\nPyJWT==2.13.0\n")
        self.tree.module(self.tree.core / "addons", "mod", ["pdfminer_six", "pyjwt"])

        self.assertEqual(self.measure(), [])

    def test_a_version_specifier_on_either_side_is_ignored(self):
        self.tree.requirements(addons="zeep==4.3.3\n")
        self.tree.module(self.tree.core / "addons", "mod", ["zeep>=4.0"])

        self.assertEqual(self.measure(), [])

    def test_an_import_name_where_a_distribution_belongs_is_a_finding(self):
        """`check_python_external_dependency` resolves the name through
        importlib.metadata, so `ldap` is wrong in the manifest for the same
        reason it is absent from the pins."""
        self.tree.requirements(addons="python-ldap==3.4.7\n")
        self.tree.module(self.tree.core / "addons", "mod", ["ldap"])

        findings = self.measure()

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].suggestion, "python-ldap")

    def test_a_comment_or_marker_on_a_pin_does_not_hide_it(self):
        self.tree.requirements(
            addons="python-ldap==3.4.7 ; sys_platform != 'win32'  # auth_ldap\n"
        )
        self.tree.module(self.tree.core / "addons", "mod", ["python-ldap"])

        self.assertEqual(self.measure(), [])


class WhichRequirementsFileApplies(PinCase):
    def test_a_core_module_may_use_either_core_file(self):
        self.tree.requirements(core="lxml==6.1.1\n", addons="qrcode==8.2\n")
        self.tree.module(self.tree.core / "addons", "a", ["lxml"])
        self.tree.module(self.tree.core / "addons", "b", ["qrcode"])

        self.assertEqual(self.measure(), [])

    def test_a_sibling_may_lean_on_the_framework_requirements(self):
        """odoo/requirements.txt is what every server process imports, so a
        sibling module declaring one of its packages is not a finding."""
        self.tree.requirements(core="beautifulsoup4==4.15.0\n", sibling="")
        self.tree.module(self.tree.sibling, "web_scraper", ["beautifulsoup4"])

        self.assertEqual(self.measure(self.tree.sibling), [])

    def test_a_sibling_may_not_lean_on_the_core_addons_requirements(self):
        """requirements-addons.txt is absent from the install command each
        sibling's own header documents, so leaning on it is the defect."""
        self.tree.requirements(core="", addons="phonenumbers==9.0.36\n", sibling="")
        self.tree.module(self.tree.sibling, "whatsapp", ["phonenumbers"])

        findings = self.measure(self.tree.sibling)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].dependency, "phonenumbers")

    def test_a_sibling_pinning_it_itself_is_clean(self):
        self.tree.requirements(
            core="", addons="phonenumbers==9.0.36\n", sibling="phonenumbers==9.0.36\n"
        )
        self.tree.module(self.tree.sibling, "whatsapp", ["phonenumbers"])

        self.assertEqual(self.measure(self.tree.sibling), [])


class TheGateRefusesToReportNothing(PinCase):
    def test_a_tree_with_no_manifest_refuses(self):
        self.tree.requirements(addons="requests==2.34.2\n")

        with self.assertRaises(SystemExit) as caught:
            self.measure()

        self.assertIn("no __manifest__.py", str(caught.exception))

    def test_a_tree_whose_manifests_declare_nothing_refuses(self):
        """Manifests but no declarations means the scan read nothing, so 0
        findings would be vacuous rather than clean."""
        self.tree.requirements(addons="requests==2.34.2\n")
        self.tree.module(self.tree.core / "addons", "mod")

        with self.assertRaises(SystemExit) as caught:
            self.measure()

        self.assertIn("declare no Python dependency", str(caught.exception))

    def test_an_empty_pin_set_is_loud_rather_than_refused(self):
        """The opposite direction needs no guard: every declaration becomes a
        finding, which cannot be mistaken for success."""
        self.tree.requirements(core="", addons="# only a comment\n")
        self.tree.module(self.tree.core / "addons", "mod", ["requests"])

        findings = self.measure()

        self.assertEqual([f.dependency for f in findings], ["requests"])

    def test_an_unparseable_manifest_is_skipped_not_crashed_on(self):
        self.tree.requirements(addons="requests==2.34.2\n")
        self.tree.module(self.tree.core / "addons", "good", ["requests"])
        broken = self.tree.core / "addons" / "broken"
        broken.mkdir()
        (broken / "__manifest__.py").write_text("{'name': unclosed")

        self.assertEqual(self.measure(), [])


if __name__ == "__main__":
    unittest.main()
