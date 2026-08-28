import ast
import logging
import re
from pathlib import Path

from lxml import etree

from odoo.tests import tagged

from .lint_case import LintCase, _module_roots

_logger = logging.getLogger(__name__)

# Only names in this family are checked. A dispatch target is an ordinary method
# name, so requiring every method name in every string to resolve would drown in
# false positives; the `action_` prefix is the fork's convention for the ones a
# view, a server action or the web client calls by name.
ACTION_NAME = re.compile(r"^action_\w+$")

# `<widget type="object">` takes its `name` from the widget registry, not the
# model, so it is not a dispatch.
DISPATCHING_TAGS = frozenset({"button", "a"})

# Two narrow shapes, deliberately. `orm.call("model", "action_x")` takes the method
# as its second string argument, and `doActionButton({name: "action_x"})` as an
# object property of a `doActionButton` call. Looser spellings mis-fire twice over:
# any action_* string near a dispatch call matches `params.name === "action_x"` in a
# mocked service, and a bare `name: "action_x"` matches a field descriptor such as
# stock_action_field.js`s `{label: _t("Action Name"), name: "action_name"}`. Neither
# is a dispatch.
JS_DISPATCH = (
    re.compile(r"""orm\.call\(\s*["'][\w.]+["']\s*,\s*["'](action_\w+)["']"""),
    re.compile(
        r"""doActionButton\s*\(\s*\{[^}]*?\bname:\s*["'](action_\w+)["']""",
        re.DOTALL,
    ),
)

_PARSER = etree.XMLParser(remove_comments=True, strip_cdata=False)

# Resolvable only outside the addons path the gate was started with. Not defects:
# `test_lint.yml` runs at `odoo/addons,addons`, so a method an `enterprise` module
# contributes to a core model is invisible there and reads as dead. Exempted by
# name rather than absorbed into a count floor, because a floor made of artefacts
# is a gate that lies about how much debt it is holding.
DEFINED_OUT_OF_SCOPE = frozenset({
    "action_validate_mandate",   # enterprise account_sepa_direct_debit
    "action_update_rights",      # enterprise documents extension of documents.sharing
    "action_edit_dashboard",     # enterprise/spreadsheet_dashboard_edition
})

# Genuinely dangling and older than this gate, each in a module whose owner has to
# decide what the caller meant -- none has a `action_view_<same suffix>` twin or any
# other near match, so renaming them here would be a guess. Named rather than
# counted so that fixing one is a line deleted from this set, and so a reader sees
# what the debt IS instead of an integer.
KNOWN_DANGLING = frozenset({
    "action_trigger_technical_analysis",   # agromarin/ai_project, inside `except
                                           # Exception`, so it fails silently
    "action_set_overtimes",                # agromarin/l10n_mx_edi_payslip tests
    "action_payslips_done",                # agromarin/l10n_mx_edi_payslip tests
    "action_invalidate_check",             # enterprise/account_reports
    "action_set_quantities_to_reservation",  # enterprise/delivery_sendcloud tests
})

EXEMPT = DEFINED_OUT_OF_SCOPE | KNOWN_DANGLING


@tagged("post_install", "-at_install")
class ButtonTargetLinter(LintCase):
    """A name dispatched to a model must be a method that exists.

    View validation already rejects a dangling `<button type="object">` -- but only
    when the module owning the view is installed, one offender at a time, on
    whoever installs it next. It sees nothing at all of the other two shapes:
    `<expr>.action_x()` in Python and `doActionButton({name: "action_x"})` in JS
    both fail when someone presses the button, in production.

    `1abf4b95135` and `25271fd8e13` renamed 303 methods `action_open_*` to
    `action_view_*`, updated the definitions and left the callers: 615 dead
    reference sites -- 328 XML buttons, 17 `python_method` server actions, 242
    Python calls, 28 JS dispatches. `base` was among them, so no database could be
    created at all. Every static lane stayed green for a day and a half.

    Static on purpose: it needs no registry, so it reports every offender in the
    tree rather than only the ones a lane happens to install.
    """

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
        except (OSError, UnicodeDecodeError):
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
            return  # a deliberately broken fixture is another gate's finding
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
        except (etree.XMLSyntaxError, OSError):
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
        """An exemption that is no longer needed must be deleted, not left standing.

        A named exemption rots the same way a count floor does -- nobody re-measures
        it, and it quietly starts excusing something that is fine while reading as
        live debt. Membership is therefore checked in both directions, as
        `testbaseline.py` and `test_architecture_doc.py` already do for their own
        lists: if one of these names acquires a definition, the debt was paid and
        the line has to go with it.

        Only `KNOWN_DANGLING` can be checked this way. `DEFINED_OUT_OF_SCOPE` names
        resolve by design at any scope wide enough to see the module that defines
        them, so "it resolves now" carries no information about those.
        """
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
        # Not an assertion: whether an exemption is reachable depends on the addons
        # path, so silence here means "not in scope", not "no longer needed". Logged
        # so a wide-scope run still surfaces the ones whose caller has gone.
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
