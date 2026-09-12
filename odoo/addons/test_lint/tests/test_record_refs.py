import csv
import functools
import io
import logging
import re
from pathlib import Path

from lxml import etree

from odoo.modules import Manifest
from odoo.modules.db import category_xml_id

from . import lint_case
from ._rules import is_test_path
from ._xml_identity import PARSER as _PARSER

_logger = logging.getLogger(__name__)

_SKIP_DIRS = {"static", "node_modules", "_vendor"}

_DECLARING_TAGS = frozenset({"record", "template", "menuitem", "asset"})

_MARKUP_TAGS = frozenset({"template"})

_REF_ATTRIBUTES = ("eval", "t-value", "context", "search")

_TEMPLATE_REF_ATTRIBUTES = ("inherit_id", "website_id")

_REGISTRY_MINTED_PREFIXES = ("field_", "selection_", "constraint_")

_HOOK_MINTED_MODULES = frozenset({"product_unspsc"})

_RE_REF_CALL = re.compile(r"\bref\(\s*['\"]([^'\"]+)['\"]")
_RE_REF_CALL_OPTIONAL = re.compile(r"\bref\(\s*['\"]([^'\"]+)['\"]\s*,\s*False\s*\)")
_RE_XML_ID_LITERAL = re.compile(r"['\"]xml_id['\"]\s*:\s*['\"]([^'\"]+)['\"]")
_RE_XML_ID_WRAPPED = re.compile(
    r"['\"]xml_id['\"]\s*:\s*[A-Za-z_][\w.]*\(\s*['\"]([^'\"]+)['\"]"
)
_RE_PCT_REF = re.compile(r"%%|%\((.*?)\)[ds]")


def _qualify(module, xmlid):
    return xmlid if "." in xmlid else f"{module}.{xmlid}"


def _is_markup(element):
    return element.tag in _MARKUP_TAGS or (
        element.tag == "field"
        and (element.get("name") == "arch" or element.get("type") in ("xml", "html"))
    )


def _is_optional_field_ref(element):
    record = element.getparent()
    while record is not None and record.tag not in ("record", "template"):
        record = record.getparent()
    if record is None:
        return False
    return (record.get("forcecreate") or "").strip().lower() in ("false", "0")


def _references_of(module, element):
    def qualified(xmlid):
        return _qualify(module, xmlid)

    if element.tag == "field" and (ref := element.get("ref")):
        if not _is_optional_field_ref(element):
            yield qualified(ref)
    if element.tag == "delete" and (ref := element.get("id")):
        yield qualified(ref)
    if uid := element.get("uid"):
        yield qualified(uid)
    if element.tag == "menuitem":
        for attribute in ("parent", "action"):
            if value := element.get(attribute):
                yield qualified(value)
    if element.tag == "template":
        for attribute in _TEMPLATE_REF_ATTRIBUTES:
            if value := element.get(attribute):
                yield qualified(value)
    if element.tag in ("menuitem", "template"):
        for group in (element.get("groups") or "").split(","):
            group = group.strip().removeprefix("-").removeprefix("!")
            if group:
                yield qualified(group)
    for attribute in _REF_ATTRIBUTES:
        source = element.get(attribute) or ""
        optional = {m.group(1) for m in _RE_REF_CALL_OPTIONAL.finditer(source)}
        for match in _RE_REF_CALL.finditer(source):
            if match.group(1) not in optional:
                yield qualified(match.group(1))
    if _is_markup(element):
        markup = etree.tostring(element, encoding="unicode")
        for match in _RE_PCT_REF.finditer(markup):
            if match.group(0) != "%%":
                yield qualified(match.group(1))


class TestRecordReferences(lint_case.LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.defined = set()
        cls.known_modules = set()
        cls.references = []
        cls.declared_models = lint_case.declared_models()
        cls.inherits = lint_case.declared_inherits()
        for manifest in Manifest.get_all_addon_manifests():
            cls.known_modules.add(manifest.name)
            cls._collect_categories(manifest)
            core = lint_case.is_core_path(str(manifest.path))
            cls._scan_xml(manifest.name, Path(manifest.path), core)
            cls._scan_csv(manifest.name, Path(manifest.path))
            cls._scan_python(manifest.name, Path(manifest.path))

    @classmethod
    def _collect_categories(cls, manifest):
        parts = (manifest.get("category") or "").split("/")
        for depth in range(1, len(parts) + 1):
            cls.defined.add(f"base.{category_xml_id(parts[:depth])}")

    @classmethod
    def _scan_xml(cls, module, root, core):
        for path in root.rglob("*.xml"):
            if _SKIP_DIRS.intersection(path.parts) or is_test_path(str(path)):
                continue
            try:
                tree = etree.parse(str(path), _PARSER).getroot()
            except etree.XMLSyntaxError:
                continue
            for element in tree.iter():
                if callable(element.tag):
                    continue
                cls._collect_definition(module, element)
                if core:
                    cls._collect_reference(module, path, element)

    @classmethod
    def _collect_definition(cls, module, element):
        xmlid = element.get("id")
        if element.tag == "template" and not xmlid:
            xmlid = element.get("t-name")
        if xmlid and element.tag in _DECLARING_TAGS:
            qualified = _qualify(module, xmlid)
            cls.defined.add(qualified)
            for parent in cls.inherits.get(element.get("model"), ()):
                cls.defined.add(f"{qualified}_{parent.replace('.', '_')}")
        for attribute in ("eval", "t-value"):
            for match in _RE_XML_ID_LITERAL.finditer(element.get(attribute) or ""):
                cls.defined.add(_qualify(module, match.group(1)))

    @classmethod
    def _collect_reference(cls, module, path, element):
        for xmlid in _references_of(module, element):
            cls.references.append((xmlid, path, element.sourceline))

    @classmethod
    def _scan_csv(cls, module, root):
        for path in root.rglob("*.csv"):
            if _SKIP_DIRS.intersection(path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue
            header = text.split("\n", 1)[0]
            delimiter = "|" if header.count("|") > header.count(",") else ","
            rows = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            if not rows.fieldnames or "id" not in rows.fieldnames:
                continue
            try:
                for row in rows:
                    if xmlid := (row.get("id") or "").strip():
                        cls.defined.add(_qualify(module, xmlid))
            except csv.Error:
                continue

    @classmethod
    def _scan_python(cls, module, root):
        for path in root.rglob("*.py"):
            if _SKIP_DIRS.intersection(path.parts):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue
            for pattern in (_RE_XML_ID_LITERAL, _RE_XML_ID_WRAPPED):
                for match in pattern.finditer(source):
                    cls.defined.add(_qualify(module, match.group(1)))

    @classmethod
    def _is_statically_undecidable(cls, ref):
        module, _, local = ref.partition(".")
        return (
            local.startswith(_REGISTRY_MINTED_PREFIXES)
            or module in _HOOK_MINTED_MODULES
            or "%" in ref
            or "{" in ref
        )

    @classmethod
    def _is_orm_minted(cls, ref):
        _module, _, local = ref.partition(".")
        if local.startswith("model_"):
            return local.removeprefix("model_") in cls._model_tokens()
        if local.startswith("module_"):
            return local.removeprefix("module_") in cls.known_modules
        return False

    @classmethod
    @functools.cache
    def _model_tokens(cls):
        return frozenset(name.replace(".", "_") for name in cls.declared_models)

    def _unresolved(self, refs):
        return [
            ref
            for ref in refs
            if ref.split(".")[0] in self.known_modules
            and ref not in self.defined
            and not self._is_statically_undecidable(ref)
            and not self._is_orm_minted(ref)
        ]

    def test_every_record_reference_resolves(self):
        unresolved = set(self._unresolved(ref for ref, _p, _l in self.references))
        missing = sorted(
            f"{path}:{lineno} -> {ref}"
            for ref, path, lineno in self.references
            if ref in unresolved
        )
        _logger.info(
            "checked %s record reference(s) against %s declared xmlid(s)",
            len(self.references),
            len(self.defined),
        )
        self.assertGreater(
            len(self.references), 5000, "the scan reached almost no references"
        )
        self.assert_ratchet(
            missing,
            "lint_record_reference",
            "reference(s) naming an xmlid no data file in the tree declares",
            "A data file that refs a missing xmlid does not degrade -- it raises "
            "`ValueError: External ID not found in the system` and the module "
            "cannot install at all. Repoint the ref at the name this fork "
            "actually uses, or delete the record that has no basis here.",
        )

    def test_the_scan_finds_the_xmlids_it_is_judging_against(self):
        self.assertGreater(len(self.defined), 10000, "almost no xmlids were found")
        for xmlid in ("base.main_company", "base.user_admin", "base.group_system"):
            self.assertIn(xmlid, self.defined, f"{xmlid} must be discoverable")

    def test_a_reference_into_an_absent_module_is_left_alone(self):
        self.assertFalse(
            self._unresolved(["no_such_module.whatever"]),
            "the optional-dependency idiom must stay lenient",
        )

    def test_a_planted_dangling_reference_is_caught(self):
        self.assertEqual(
            self._unresolved(["base.no_such_record_at_all"]),
            ["base.no_such_record_at_all"],
        )

    def test_an_orm_minted_xmlid_is_not_judged(self):
        for ref in (
            "base.model_res_partner",
            "base.field_res_partner__name",
            "base.module_web",
            "base.module_category_sales_sales",
            "stock.ir_cron_scheduler_action_ir_actions_server",
        ):
            self.assertFalse(
                self._unresolved([ref]), f"{ref} is minted by the ORM, not declared"
            )

    def test_a_minted_looking_xmlid_naming_no_model_or_module_is_judged(self):
        self.assertEqual(
            self._unresolved(["base.model_res_partnerr", "base.module_no_such"]),
            ["base.model_res_partnerr", "base.module_no_such"],
        )

    def test_every_reference_shape_the_loader_resolves_is_collected(self):
        root = etree.fromstring(
            b"""
            <odoo context="{'a': ref('ctx_ref')}">
                <record id="r" model="m" context="{'b': ref('rec_ctx')}">
                    <field name="f1" ref="field_ref"/>
                    <field name="f2" eval="[ref('eval_ref'), ref('opt', False)]"/>
                    <field name="f3" search="[('id', '=', ref('search_ref'))]"/>
                    <field name="arch" type="xml">
                        <button name="%(pct_ref)d"/>
                        <span>%%(year)s</span>
                    </field>
                </record>
                <template id="t" inherit_id="tpl_parent" groups="g1,!g2"/>
                <menuitem id="m1" parent="menu_parent" action="menu_action"/>
                <delete model="m" id="delete_ref"/>
                <function model="m" name="f" uid="fn_uid" eval="[ref('fn_ref')]"/>
            </odoo>
            """,
            _PARSER,
        )
        collected = {
            xmlid.removeprefix("base.")
            for element in root.iter()
            if not callable(element.tag)
            for xmlid in _references_of("base", element)
        }
        self.assertEqual(
            collected,
            {
                "ctx_ref",
                "rec_ctx",
                "field_ref",
                "eval_ref",
                "search_ref",
                "pct_ref",
                "tpl_parent",
                "g1",
                "g2",
                "menu_parent",
                "menu_action",
                "delete_ref",
                "fn_uid",
                "fn_ref",
            },
        )
