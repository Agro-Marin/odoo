import csv
import io
import logging
import re
from pathlib import Path

from lxml import etree

from odoo.modules import Manifest

from . import lint_case
from ._rules import is_test_path
from ._xml_identity import PARSER as _PARSER

_logger = logging.getLogger(__name__)

_SKIP_DIRS = {"static", "node_modules", "_vendor"}

_DECLARING_TAGS = frozenset({"record", "template", "menuitem", "report", "act_window"})

# The ORM mints these itself while reflecting models, fields and modules, so no
# data file declares them and a static scan can only guess wrong.
_ORM_MINTED_PREFIXES = ("model_", "field_", "selection_", "constraint_", "module_")

# Modules whose records are created by a post-init hook rather than a data file.
# Named here so the gate stands aside deliberately instead of being blind: a
# module added here is one nothing checks, so add only with the hook in hand.
_HOOK_MINTED_MODULES = frozenset({"product_unspsc"})

_RE_REF_CALL = re.compile(r"\bref\(\s*['\"]([^'\"]+)['\"]")
_RE_XML_ID_LITERAL = re.compile(r"['\"]xml_id['\"]\s*:\s*['\"]([^'\"]+)['\"]")


def _qualify(module, xmlid):
    return xmlid if "." in xmlid else f"{module}.{xmlid}"


class TestRecordReferences(lint_case.LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.defined = set()
        cls.known_modules = set()
        cls.references = []
        for manifest in Manifest.all_addon_manifests():
            cls.known_modules.add(manifest.name)
            cls._scan_xml(manifest.name, Path(manifest.path))
            cls._scan_csv(manifest.name, Path(manifest.path))
            cls._scan_python(manifest.name, Path(manifest.path))

    @classmethod
    def _scan_xml(cls, module, root):
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
                cls._collect_reference(module, path, element)

    @classmethod
    def _collect_definition(cls, module, element):
        xmlid = element.get("id")
        if xmlid and element.tag in _DECLARING_TAGS:
            qualified = _qualify(module, xmlid)
            cls.defined.add(qualified)
            if element.get("model") == "product.product":
                # Loading a product.product also creates its template, under the
                # product's own xmlid with this suffix.
                cls.defined.add(f"{qualified}_product_template")
        for attribute in ("eval", "t-value"):
            for match in _RE_XML_ID_LITERAL.finditer(element.get(attribute) or ""):
                cls.defined.add(_qualify(module, match.group(1)))

    @classmethod
    def _collect_reference(cls, module, path, element):
        # `ref` is an xmlid only on <field>; elsewhere in a view arch it is an
        # ordinary attribute of the rendered element.
        if element.tag == "field" and (ref := element.get("ref")):
            cls.references.append((_qualify(module, ref), path, element.sourceline))
        for attribute in ("eval", "t-value"):
            for match in _RE_REF_CALL.finditer(element.get(attribute) or ""):
                cls.references.append(
                    (_qualify(module, match.group(1)), path, element.sourceline)
                )

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
        # Data-loading helpers mint xmlids from a literal in Python
        # (pos_restaurant builds its demo config this way), so the declaration
        # is real but lives outside any data file.
        for path in root.rglob("*.py"):
            if _SKIP_DIRS.intersection(path.parts):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue
            for match in _RE_XML_ID_LITERAL.finditer(source):
                cls.defined.add(_qualify(module, match.group(1)))

    @classmethod
    def _is_statically_undecidable(cls, ref):
        module, _, local = ref.partition(".")
        return (
            local.startswith(_ORM_MINTED_PREFIXES)
            or module in _HOOK_MINTED_MODULES
            # A ref carrying a format placeholder is assembled at load time.
            or "%" in ref
            or "{" in ref
        )

    def _unresolved(self, refs):
        return [
            ref
            for ref in refs
            if ref.split(".")[0] in self.known_modules
            and ref not in self.defined
            and not self._is_statically_undecidable(ref)
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
        ):
            self.assertFalse(
                self._unresolved([ref]), f"{ref} is minted by the ORM, not declared"
            )

    def test_a_format_placeholder_reference_is_not_judged(self):
        self.assertFalse(self._unresolved(["account.%s_ri_tax_vat_0_compras"]))
        self.assertFalse(self._unresolved(["account.{}_ri_tax_vat_21_compras"]))

    def test_an_unqualified_reference_is_read_as_its_own_module(self):
        self.assertEqual(_qualify("sale", "sale_order_tree"), "sale.sale_order_tree")
        self.assertEqual(_qualify("sale", "base.group_user"), "base.group_user")
        self.assertFalse(
            [ref for ref, _p, _l in self.references if "." not in ref],
            "every collected reference must carry a module",
        )
