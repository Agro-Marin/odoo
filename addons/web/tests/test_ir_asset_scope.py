# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo.modules import Manifest
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "asset_scope")
class TestUnitTestAssetScope(TransactionCase):
    """``web.assets_unit_tests_setup`` scoping for HOOT runs.

    Without a scope the unit-test page executes every installed addon's
    ``src``, whose registry/patch side effects are global while mock models
    are opt-in per suite — so one addon's ``src`` reaches for models another
    addon's suite never defined.
    """

    def test_closure_follows_manifest_dependencies(self):
        """A dependency reached only through an intermediate is still included.

        Driven off a synthetic graph rather than a real addon: the property is
        about the walk, and every addon deep enough to exercise it (``mail``,
        which reaches ``base`` only via ``html_editor`` → ``bus`` → ``web``)
        sits *above* ``web`` in the dependency order, so it cannot be installed
        in the database ``web``'s own suite runs against.
        """
        graph = {
            "a": {"depends": ["b"]},
            "b": {"depends": ["c"]},
            "c": {"depends": ["base"]},
            "base": {"depends": []},
        }
        IrAsset = self.env["ir.asset"]

        with (
            patch.object(
                type(IrAsset),
                "_get_installed_addons_list",
                return_value=frozenset(graph),
            ),
            patch.object(Manifest, "for_addon", staticmethod(graph.get)),
        ):
            closure = IrAsset._get_unit_test_scope_addons("a")

        self.assertEqual(closure, frozenset(graph))

    def test_closure_excludes_addons_that_merely_depend_on_the_scope(self):
        closure = self.env["ir.asset"]._get_unit_test_scope_addons("web")

        self.assertIn("web", closure)
        self.assertNotIn("mail", closure)

    def test_uninstalled_scope_yields_no_addons(self):
        self.assertFalse(
            self.env["ir.asset"]._get_unit_test_scope_addons("no_such_addon")
        )

    def test_active_addons_are_narrowed_to_the_closure(self):
        IrAsset = self.env["ir.asset"]
        unscoped = set(IrAsset._get_active_addons_list())

        scoped = set(IrAsset._get_active_addons_list(unit_test_scope="web"))

        self.assertLessEqual(scoped, unscoped)
        self.assertIn("web", scoped)
        if "mail" in unscoped:
            self.assertNotIn("mail", scoped)

    def test_no_scope_leaves_the_addon_list_untouched(self):
        """The scope must be inert until a run asks for one."""
        IrAsset = self.env["ir.asset"]

        self.assertEqual(
            set(IrAsset._get_active_addons_list()),
            set(IrAsset._get_active_addons_list(unit_test_scope=None)),
        )

    def test_scope_is_ignored_outside_a_request(self):
        """No request (or a non-runner route) must not touch the cache key."""
        self.assertEqual(self.env["ir.asset"]._get_unit_test_scope(), "")
        self.assertNotIn("unit_test_scope", self.env["ir.asset"]._get_asset_params())
