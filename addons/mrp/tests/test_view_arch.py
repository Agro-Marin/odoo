"""Guards for view arches whose resolution is the whole behaviour."""

from lxml import etree

from odoo import Command
from odoo.tests import tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestMrpViewArch(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # `result_package_id` is behind stock.group_tracking_lot, and `get_view`
        # drops what the reader may not see, so without this the package
        # assertions below would pass against an absent node.
        cls.env.user.group_ids = [
            Command.link(cls.env.ref("stock.group_tracking_lot").id)
        ]

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

    def _package_column(self, xml_id):
        arch = self._arch(xml_id, "stock.move.line", "list")
        return arch.xpath("//field[@name='result_package_id'][@widget='package_m2o']")

    def _move_line_context(self, xml_id):
        arch = self._arch(xml_id, "stock.move", "form")
        return arch.xpath("//field[@name='move_line_ids']")[0].get("context")

    def test_component_operations_hide_the_destination_package(self):
        """Components are consumed unpacked, so the column invites a no-op.

        The list is a lazily loaded sub-view, shared with pickings and with the
        by-product form, so the attribute cannot be scoped by editing the parent
        form. It goes on a primary variant of the list instead, the way
        mrp_subcontracting already scopes the same list.
        """
        column = self._package_column("mrp.view_stock_move_line_operation_tree_raw")

        self.assertTrue(column, "the column must still resolve")
        self.assertEqual(column[0].get("column_invisible"), "True")

    def test_component_form_actually_loads_that_list(self):
        """The primary list is worthless unless the raw form points at it."""
        context = self._move_line_context("mrp.view_stock_move_form_operations_raw")

        self.assertIn("mrp.view_stock_move_line_operation_tree_raw", context or "")

    def test_other_operations_keep_the_destination_package(self):
        """Only components lose the column.

        `view_mrp_stock_move_operations` is the form behind both `move_raw_ids`
        and `move_byproduct_ids` on the order (views/mrp_production_views.xml),
        and produced goods can be packed, so it keeps the shared list.
        """
        column = self._package_column("stock.view_stock_move_line_operation_tree")
        self.assertTrue(column, "the column must still resolve")
        self.assertIsNone(column[0].get("column_invisible"))

        context = self._move_line_context("mrp.view_mrp_stock_move_operations")
        self.assertNotIn("mrp.view_stock_move_line_operation_tree_raw", context or "")
