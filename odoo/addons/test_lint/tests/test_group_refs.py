import ast
import logging
from pathlib import Path

from lxml import etree

from odoo.modules import Manifest

from . import lint_case
from ._rules import is_test_path
from ._xml_identity import PARSER as _PARSER

_logger = logging.getLogger(__name__)

_SKIP_DIRS = {"static", "node_modules", "_vendor"}

_GROUP_METHODS = frozenset({"has_group", "has_groups", "_has_group"})


class _CallVisitor(ast.NodeVisitor):
    def __init__(self):
        self.specs = []

    def visit_Call(self, node):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _GROUP_METHODS
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            self.specs.append((node.args[0].value, node.lineno))
        self.generic_visit(node)


class TestGroupReferences(lint_case.LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.defined = set()
        cls.known_modules = set()
        cls.references = []
        for manifest in Manifest.all_addon_manifests():
            cls.known_modules.add(manifest.name)
            for path in Path(manifest.path).rglob("*.xml"):
                if _SKIP_DIRS.intersection(path.parts):
                    continue
                try:
                    root = etree.parse(str(path), _PARSER).getroot()
                except etree.XMLSyntaxError:
                    continue
                for element in root.iter():
                    if callable(element.tag):
                        continue
                    cls._collect_definition(manifest.name, element)
                    if not is_test_path(str(path)):
                        cls._collect_xml_references(manifest.name, path, element)

        for manifest in Manifest.all_addon_manifests():
            for path in Path(manifest.path).rglob("*.py"):
                if _SKIP_DIRS.intersection(path.parts) or is_test_path(str(path)):
                    continue
                cls._collect_python_references(manifest.name, path)

    @classmethod
    def _collect_definition(cls, module, element):
        if element.tag != "record" or element.get("model") != "res.groups":
            return
        if xmlid := element.get("id"):
            cls.defined.add(cls._qualify(module, xmlid))

    @classmethod
    def _collect_xml_references(cls, module, path, element):
        for attribute in ("groups", "t-groups"):
            if spec := element.get(attribute):
                cls._collect_spec(module, path, element.sourceline, spec)

    @classmethod
    def _collect_python_references(cls, module, path):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            return
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return
        visitor = _CallVisitor()
        visitor.visit(tree)
        for spec, lineno in visitor.specs:
            cls._collect_spec(module, path, lineno, spec)

    @classmethod
    def _collect_spec(cls, module, path, lineno, spec):
        for ref in cls._tokens(module, spec):
            cls.references.append((ref, path, lineno))

    @classmethod
    def _tokens(cls, module, spec):
        refs = []
        for token in spec.split(","):
            token = token.strip().removeprefix("!")
            if not token or token == ".":
                continue
            refs.append(cls._qualify(module, token))
        return refs

    @staticmethod
    def _qualify(module, xmlid):
        return xmlid if "." in xmlid else f"{module}.{xmlid}"

    def _unresolved(self, refs):
        return [
            ref
            for ref in refs
            if ref.split(".")[0] in self.known_modules and ref not in self.defined
        ]

    def test_every_group_reference_resolves(self):
        unresolved = set(self._unresolved(ref for ref, _p, _l in self.references))
        missing = [
            f"{path}:{lineno} -> {ref}"
            for ref, path, lineno in self.references
            if ref in unresolved
        ]
        _logger.info(
            "checked %s group reference(s) against %s defined group(s)",
            len(self.references),
            len(self.defined),
        )
        self.assertGreater(
            len(self.references), 500, "the scan reached almost no group references"
        )
        self.assert_ratchet(
            sorted(missing),
            "lint_group_reference",
            "group reference(s) naming a group their own module never defines",
            "A reference that cannot resolve answers 'not a member', and a "
            "negated one answers 'everyone' -- so a typo in `groups=\"!x.y\"` "
            "shows the node to every user and nothing raises. Fix the spelling, "
            "or point it at a group that exists.",
        )

    def test_a_reference_into_an_absent_module_is_left_alone(self):
        absent = [
            ref
            for ref, _path, _lineno in self.references
            if ref.split(".")[0] not in self.known_modules
        ]
        _logger.info("%s reference(s) name a module outside this tree", len(absent))
        self.assertNotIn(
            "no_such_module.group_x",
            self.defined,
            "fixture: an absent module must not appear as a definition",
        )

    def test_the_scan_finds_the_groups_it_is_judging_against(self):
        self.assertGreater(len(self.defined), 100, "almost no groups were found")
        for xmlid in (
            "base.group_system",
            "base.group_user",
            "base.group_no_one",
            "base.group_portal",
        ):
            self.assertIn(xmlid, self.defined, f"{xmlid} must be discoverable")

    def test_the_scan_reads_both_python_and_xml(self):
        suffixes = {Path(path).suffix for _ref, path, _lineno in self.references}
        self.assertIn(".py", suffixes, "no Python group reference was collected")
        self.assertIn(".xml", suffixes, "no XML group reference was collected")

    def test_a_planted_typo_is_caught_in_both_polarities(self):
        spec = "base.group_sytem,!base.group_systen"
        refs = self._tokens("base", spec)
        self.assertEqual(refs, ["base.group_sytem", "base.group_systen"])
        self.assertEqual(
            self._unresolved(refs),
            refs,
            "a typo must be caught whether or not the reference is negated",
        )

    def test_a_correct_spec_is_not_flagged(self):
        refs = self._tokens("base", "base.group_system,!base.group_portal")
        self.assertEqual(refs, ["base.group_system", "base.group_portal"])
        self.assertFalse(self._unresolved(refs))

    def test_an_absent_module_is_not_flagged(self):
        refs = self._tokens("base", "no_such_module.group_x,!no_such_module.group_y")
        self.assertFalse(
            self._unresolved(refs),
            "the optional-dependency idiom must stay lenient",
        )

    def test_an_unqualified_reference_is_read_as_its_own_module(self):
        self.assertEqual(
            self._qualify("fleet", "fleet_group_manager"), "fleet.fleet_group_manager"
        )
        self.assertEqual(self._qualify("fleet", "base.group_user"), "base.group_user")
        self.assertFalse(
            [ref for ref, _p, _l in self.references if "." not in ref],
            "every collected reference must carry a module",
        )
