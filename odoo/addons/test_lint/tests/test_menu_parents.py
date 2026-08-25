import logging
from pathlib import Path

from lxml import etree

from odoo.modules import Manifest

from . import lint_case
from ._xml_identity import PARSER as _PARSER

_logger = logging.getLogger(__name__)


class TestMenuParents(lint_case.LintCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.defined = set()
        cls.references = []
        cls.known_modules = set()
        for manifest in Manifest.all_addon_manifests():
            cls.known_modules.add(manifest.name)
            core = lint_case.is_core_path(str(manifest.path))
            for path in Path(manifest.path).rglob("*.xml"):
                if {"static", "node_modules", "_vendor"}.intersection(path.parts):
                    continue
                try:
                    root = etree.parse(str(path), _PARSER).getroot()
                except etree.XMLSyntaxError:
                    continue
                for element in root.iter():
                    if callable(element.tag):
                        continue
                    cls._collect(manifest.name, path, element, core)

    @classmethod
    def _collect(cls, module, path, element, core):
        is_menu = element.tag == "menuitem" or (
            element.tag == "record" and element.get("model") == "ir.ui.menu"
        )
        if is_menu and (xmlid := element.get("id")):
            cls.defined.add(cls._qualify(module, xmlid))
        if core and element.tag == "menuitem" and (parent := element.get("parent")):
            cls.references.append(
                (cls._qualify(module, parent), path, element.sourceline)
            )

    @staticmethod
    def _qualify(module, xmlid):
        return xmlid if "." in xmlid else f"{module}.{xmlid}"

    def test_every_menu_parent_exists(self):
        missing = [
            f"{path}:{lineno} -> {parent}"
            for parent, path, lineno in self.references
            if parent.split(".")[0] in self.known_modules and parent not in self.defined
        ]
        _logger.info(
            "checked %s menu parent reference(s) against %s defined menu(s)",
            len(self.references),
            len(self.defined),
        )
        self.assertGreater(
            len(self.references), 100, "the scan reached almost no menu references"
        )
        self.assert_ratchet(
            sorted(missing),
            "lint_menu_parent",
            "menuitem parent(s) naming a menu no data file defines",
            "Repoint it at a menu that exists: loading the file raises "
            "`External ID not found in the system` and fails the whole install.",
        )

    def test_the_scan_finds_the_menus_it_is_judging_against(self):
        self.assertGreater(len(self.defined), 900, "almost no menus were found")
        self.assertIn(
            "account.menu_finance_configuration",
            self.defined,
            "the menu the l10n configuration entries hang off is missing",
        )
