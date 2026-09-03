"""Guards for view arches whose resolution is the whole behaviour."""

from lxml import etree

from odoo.tests import tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestMrpViewArch(TestMrpCommon):
    def _arch(self, xml_id, model, view_type):
        return etree.fromstring(
            self.env[model].get_view(self.env.ref(xml_id).id, view_type)["arch"]
        )

    def test_production_search_offers_the_lot_it_produces(self):
        """A serial number must lead back to the order that produced it.

        The work order search already offers it (`finished_lot_ids`); the
        manufacturing order search did not, so the only route from a serial to
        its order was traceability.
        """
        arch = self._arch("mrp.view_mrp_production_filter", "mrp.production", "search")
        self.assertTrue(
            arch.xpath("//field[@name='lot_producing_ids']"),
            "the Search Production view must expose lot_producing_ids",
        )

        mo, _bom, product, _p1, _p2 = self.generate_mo(
            tracking_final="serial", qty_final=1
        )
        lot = self.env["stock.lot"].create(
            {"name": "SN-SEARCHABLE-0001", "product_id": product.id}
        )
        mo.lot_producing_ids = lot

        # The default filter_domain the view builds for a Many2many is
        # [(name, 'ilike', self)]; prove it actually resolves the lot name.
        found = self.env["mrp.production"].search(
            [("lot_producing_ids", "ilike", lot.name)]
        )
        self.assertIn(mo, found)

    def test_kit_bom_hides_the_manufacturing_lead_times(self):
        """A kit is exploded, never manufactured, so its lead times mean nothing.

        `picking_type_id` already carried the condition; `produce_delay`,
        `days_to_prepare_mo` and the Compute button beside them did not, so a kit
        form offered three inputs that no manufacturing path reads.
        """
        arch = self._arch("mrp.mrp_bom_form_view", "mrp.bom", "form")

        group = arch.xpath("//field[@name='produce_delay']/ancestor::group[1]")
        self.assertTrue(group, "produce_delay must still live in a group")
        self.assertEqual(group[0].get("invisible"), "type == 'phantom'")

        for fname in ("produce_delay", "days_to_prepare_mo"):
            node = arch.xpath(f"//field[@name='{fname}']")
            self.assertTrue(node, f"{fname} must still be on the form")
            self.assertIsNone(
                node[0].get("invisible"),
                f"{fname} must inherit the condition from its group, not repeat it",
            )

        # The normal-BoM inputs beside them keep their own narrower condition.
        batch = arch.xpath("//field[@name='batch_size']")
        self.assertTrue(batch)
