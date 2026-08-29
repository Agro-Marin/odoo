import ast
import logging
import re
from pathlib import Path

from lxml import etree

from odoo.tests import tagged

from .lint_case import LintCase, _module_roots

_logger = logging.getLogger(__name__)

ACTION_NAME = re.compile(r"^action_\w+$")

DISPATCHING_TAGS = frozenset({"button", "a"})

JS_DISPATCH = (
    re.compile(r"""orm\.call\(\s*["'][\w.]+["']\s*,\s*["'](action_\w+)["']"""),
    re.compile(
        r"""doActionButton\s*\(\s*\{[^}]*?\bname:\s*["'](action_\w+)["']""",
        re.DOTALL,
    ),
)

_PARSER = etree.XMLParser(remove_comments=True, strip_cdata=False)

DEFINED_OUT_OF_SCOPE = frozenset(
    {
        "action_validate_mandate",
        "action_update_rights",
        "action_edit_dashboard",
    }
)

KNOWN_DANGLING = frozenset(
    {
        "action_trigger_technical_analysis",
        "action_set_overtimes",
        "action_payslips_done",
        "action_invalidate_check",
        "action_set_quantities_to_reservation",
    }
)

EXEMPT = DEFINED_OUT_OF_SCOPE | KNOWN_DANGLING


@tagged("post_install", "-at_install")
class ButtonTargetLinter(LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.defined = set()
        cls.dispatches = []
        scanners = {
            ".py": cls._scan_python,
            ".xml": cls._scan_xml,
            ".js": cls._scan_js,
        }
        for root in _module_roots():
            for path in Path(root).rglob("*"):
                if "__pycache__" in path.parts:
                    continue
                if scan := scanners.get(path.suffix):
                    scan(path)
        _logger.info(
            "%s method definitions, %s dispatch sites",
            len(cls.defined),
            len(cls.dispatches),
        )

    @classmethod
    def _read(cls, path):
        try:
            return path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            return None

    @classmethod
    def _scan_python(cls, path):
        source = cls._read(path)
        if source is None:
            return
        cls.defined.update(re.findall(r"\bdef ([A-Za-z_]\w*)", source))
        if "action_" not in source:
            return
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and ACTION_NAME.match(node.func.attr)
            ):
                cls.dispatches.append((path, node.lineno, node.func.attr, "call"))

    @classmethod
    def _scan_xml(cls, path):
        try:
            tree = etree.parse(str(path), _PARSER)
        except etree.XMLSyntaxError, OSError:
            return
        for element in tree.iter():
            name = element.get("name")
            if (
                element.tag in DISPATCHING_TAGS
                and element.get("type") == "object"
                and name
                and ACTION_NAME.match(name)
            ):
                cls.dispatches.append((path, element.sourceline, name, "button"))
            elif element.tag == "field" and name == "python_method":
                target = (element.text or "").strip()
                if ACTION_NAME.match(target):
                    cls.dispatches.append(
                        (path, element.sourceline, target, "python_method"),
                    )

    @classmethod
    def _scan_js(cls, path):
        source = cls._read(path)
        if source is None or "action_" not in source:
            return
        for pattern in JS_DISPATCH:
            for match in pattern.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                cls.dispatches.append((path, line, match.group(1), "js"))

    def test_known_dangling_entries_are_still_dangling(self):
        paid = sorted(KNOWN_DANGLING & self.defined)
        self.assertFalse(
            paid,
            f"{len(paid)} name(s) in KNOWN_DANGLING now resolve to a real method: "
            + ", ".join(paid)
            + ". The debt is paid -- delete them from the set so the gate goes back "
            "to enforcing them.",
        )

    def test_dispatched_names_exist(self):
        self.assertTrue(self.dispatches, "the scan found no dispatch sites at all")
        offenders = [
            f"{path}:{line} ({kind}) {name}"
            for path, line, name, kind in self.dispatches
            if name not in self.defined and name not in EXEMPT
        ]
        self.assert_ratchet(
            sorted(offenders),
            "lint_dispatch_target",
            "dispatch(es) naming a method that is defined nowhere in the tree",
            "Rename the caller with the method, or restore the method. Only the XML "
            "ones fail at install; a Python or JS dispatch fails when a user presses "
            "the button.",
        )
        dispatched = {name for _, _, name, _ in self.dispatches}
        if unused := sorted(EXEMPT - dispatched):
            _logger.info(
                "%s exemption(s) not in scope on this addons path -- no dispatch "
                "reaches them here, so this run neither enforces nor clears them. "
                "A wide run reporting the same names means the caller is gone and "
                "the entry can be deleted: %s",
                len(unused),
                ", ".join(unused),
            )
