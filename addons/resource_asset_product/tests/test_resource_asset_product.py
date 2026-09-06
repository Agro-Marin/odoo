from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResourceAssetProduct(TransactionCase):
    def test_kind_follows_the_product(self):
        vehicle = self.env.ref("resource_asset.kind_vehicle")
        template = self.env["product.template"].create(
            {"name": "Pickup", "asset_kind_id": vehicle.id}
        )
        asset = self.env["resource.asset"].create(
            {"name": "Pickup 1", "product_id": template.product_variant_id.id}
        )
        self.assertEqual(asset.kind_id, vehicle)
        self.assertEqual(asset.product_tmpl_id, template)
        self.assertEqual(template.asset_count, 1)
        self.assertEqual(
            template.action_view_assets()["domain"],
            [("product_tmpl_id", "=", template.id)],
        )

    def test_an_explicit_kind_survives_a_product_without_one(self):
        tool = self.env.ref("resource_asset.kind_tool")
        template = self.env["product.template"].create({"name": "Wrench"})
        asset = self.env["resource.asset"].create(
            {
                "name": "Wrench 1",
                "product_id": template.product_variant_id.id,
                "kind_id": tool.id,
            }
        )
        self.assertEqual(asset.kind_id, tool)
