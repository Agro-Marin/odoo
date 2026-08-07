import logging
from pathlib import Path

from lxml import etree

from odoo.modules import Manifest

from . import lint_case

_logger = logging.getLogger(__name__)

_PARSER = etree.XMLParser(remove_comments=False, strip_cdata=False)


class TestMenuParents(lint_case.LintCase):
    # Every `<menuitem parent="...">` must name a menu some data file defines.
    #
    # A missing parent is not a cosmetic problem. `convert.py:_tag_menuitem`
    # resolves it through `id_get`, which raises `ValueError: External ID not
    # found in the system` -- during module *loading*, so the install of every
    # database that pulls the module in aborts and the registry fails to load.
    #
    # Nothing caught this. The module owning the reference installs fine on its
    # own (its dependency provides the menu, until it does not); it only breaks
    # in combination, so the module's own test suite is green, and the failure
    # arrives as a registry crash in an unrelated install.
    #
    # It is precisely the shape a fork produces. Commit 6cd8a09a646 removed
    # `account/views/account_menuitem.xml` -- superseded by the base_account
    # split -- taking `account.account_account_menu` and
    # `account.account_invoicing_menu` with it, and left four `parent="..."`
    # references in `l10n_it_edi`, `l10n_latam_invoice_document`,
    # `l10n_tr_nilvera_einvoice_extended` and `l10n_cz` pointing at nothing.
    # Installing `l10n_ar` (which depends on l10n_latam_invoice_document)
    # alongside `account` was enough to fail the whole registry.
    #
    # Scoped to menus deliberately. The same question can be asked of every
    # `ref=`/`eval="ref(...)"` in the tree, but most xmlids there are generated
    # rather than written -- `model_*`, `field_*`, `constraint_*`,
    # `selection__*`, a product variant's `*_product_template` companion,
    # `base.lang_*` -- and a rule reporting 61 findings of which 57 are
    # generated is a rule nobody reads. A menu parent is always written in a
    # data file, so this half has no false-positive surface at all.

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
        """Record menus this element defines, and the parent it references."""
        is_menu = element.tag == "menuitem" or (
            element.tag == "record" and element.get("model") == "ir.ui.menu"
        )
        if is_menu and (xmlid := element.get("id")):
            cls.defined.add(cls._qualify(module, xmlid))
        # References are collected from this repository only: a dangling parent
        # in a sibling checkout is not this branch's to repoint, exactly as
        # every other file-based gate here is scoped.
        if core and element.tag == "menuitem" and (parent := element.get("parent")):
            cls.references.append(
                (cls._qualify(module, parent), path, element.sourceline)
            )

    @staticmethod
    def _qualify(module, xmlid):
        return xmlid if "." in xmlid else f"{module}.{xmlid}"

    def test_every_menu_parent_exists(self):
        # A parent in a module this addons_path does not carry is skipped: the
        # menu can only ever be missing because the module is absent, which is
        # a deployment fact rather than a broken reference.
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
            MISSING_PARENT_FLOOR,
            "menuitem parent(s) naming a menu no data file defines",
            "Repoint it at a menu that exists: loading the file raises "
            "`External ID not found in the system` and fails the whole install.",
        )

    def test_the_scan_finds_the_menus_it_is_judging_against(self):
        # The gate above passes trivially if `defined` is somehow empty, since
        # every reference would then be to an unknown module. Anchor it.
        self.assertGreater(len(self.defined), 1000, "almost no menus were found")
        self.assertIn(
            "account.menu_finance_configuration",
            self.defined,
            "the menu the l10n configuration entries hang off is missing",
        )


# The four this gate ships red-on-arrival, all from the same fork regression:
# commit 6cd8a09a646 removed `account/views/account_menuitem.xml` and left
# `account.account_account_menu` (l10n_it_edi, l10n_latam_invoice_document,
# l10n_tr_nilvera_einvoice_extended) and `account.account_invoicing_menu`
# (l10n_cz) pointing at nothing. Repointing all four at
# `account.menu_finance_configuration` -- where nine other l10n modules already
# hang their configuration entries -- takes this to 0 and lets those modules
# install again.
MISSING_PARENT_FLOOR = 4
