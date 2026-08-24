from unittest.mock import patch

import odoo.tests


@odoo.tests.common.tagged("post_install", "-at_install")
class TestIrAsset(odoo.tests.HttpCase):
    def test_01_website_specific_assets(self):
        IrAsset = self.env["ir.asset"]
        Website = self.env["website"]

        website_1 = Website.create({"name": "Website 1"})
        website_2 = Website.create({"name": "Website 2"})

        assets = IrAsset.create(
            [
                {
                    "key": "test0",
                    "name": "0",
                    "bundle": "test_bundle.irasset",
                    "path": "/website/test/base0.css",
                },
                {
                    "key": "test1",
                    "name": "1",
                    "bundle": "test_bundle.irasset",
                    "path": "/website/test/base1.css",
                },
                {
                    "key": "test2",
                    "name": "2",
                    "bundle": "test_bundle.irasset",
                    "path": "/website/test/base2.css",
                },
            ]
        )

        # For website 1, modify asset 1 and disable asset 2.
        assets[1].with_context(website_id=website_1.id).write(
            {
                "path": "/website/test/specific1.css",
            }
        )
        assets[2].with_context(website_id=website_1.id).write(
            {
                "active": False,
            }
        )

        files = IrAsset._get_asset_paths(
            "test_bundle.irasset", {"website_id": website_1.id}
        )
        self.assertEqual(
            len(files), 2, "There should be two assets in the specific website."
        )
        self.assertEqual(
            files[0][0],
            "/website/test/base0.css",
            "First asset should be the same as the base one.",
        )
        self.assertEqual(
            files[1][0],
            "/website/test/specific1.css",
            "Second asset should be the specific one.",
        )

        files = IrAsset._get_asset_paths(
            "test_bundle.irasset", {"website_id": website_2.id}
        )
        self.assertEqual(
            len(files), 3, "All three assets should be in the unmodified website."
        )
        self.assertEqual(
            files[0][0],
            "/website/test/base0.css",
            "First asset should be the base one.",
        )
        self.assertEqual(
            files[1][0],
            "/website/test/base1.css",
            "Second asset should be the base one.",
        )
        self.assertEqual(
            files[2][0],
            "/website/test/base2.css",
            "Third asset should be the base one.",
        )


@odoo.tests.common.tagged("post_install", "-at_install")
class TestSpecificAssetScope(odoo.tests.common.TransactionCase):
    """A website-specific record hides the generic one it was copied from.
    Records are fetched for a whole include closure in one query, so that
    arbitration has to stay scoped to the bundle: a COW write that also moves
    the record to another bundle leaves the pair straddling two bundles of the
    same closure, and arbitrating across the batch drops the generic one from a
    bundle it still belongs to.
    """

    def test_a_specific_record_does_not_hide_a_generic_one_in_another_bundle(self):
        IrAsset = self.env["ir.asset"]
        website = self.env["website"].create({"name": "Scope"})
        path = "/web/static/src/core/utils/objects.js"
        other = "/web/static/src/core/utils/arrays.js"

        generic = IrAsset.create(
            {
                "key": "scope.probe",
                "name": "generic",
                "bundle": "scope.outer",
                "path": path,
            }
        )
        # COW: the specific copy keeps the key but lands in the included bundle
        generic.with_context(website_id=website.id).write(
            {"bundle": "scope.inner", "path": other}
        )
        specific = IrAsset.search(
            [("key", "=", "scope.probe"), ("website_id", "=", website.id)]
        )
        self.assertTrue(specific)
        self.assertEqual(generic.bundle, "scope.outer")
        self.assertEqual(specific.bundle, "scope.inner")

        closure = {
            "scope.outer": (("an_addon", ["include", "scope.inner"]),),
        }
        with patch.object(
            type(IrAsset), "_get_manifest_assets", lambda _s, addons: closure
        ):
            self.env.registry.clear_cache("assets")
            resolved = IrAsset._get_asset_paths.__wrapped__(
                IrAsset, "scope.outer", {"website_id": website.id}
            )

        # the include is a manifest command, and a record left at the default
        # sequence is applied after those, so the included bundle comes first
        self.assertEqual(
            [entry.path for entry in resolved],
            [other, path],
            "the generic record still owns its own bundle's slot",
        )
