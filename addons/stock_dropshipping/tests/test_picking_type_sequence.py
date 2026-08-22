from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDropshipPickingTypeSequence(TransactionCase):
    """`warehouse_id` moves by compute here, and the prefix has to follow it.

    `stock` alone cannot stage this: its `_compute_warehouse_id` depends on
    `company_id`, and `_check_company_change` forbids moving a type between
    companies, so the field only ever settles at create time. This module adds
    `default_location_src_id` and `default_location_dest_id` to that compute,
    which is what makes an ordinary location write hand a warehouse-less
    operation type a warehouse -- with no `warehouse_id` anywhere in the payload.
    """

    def test_a_warehouse_arriving_by_compute_carries_the_prefix_with_it(self):
        company = self.env["res.company"].create({"name": "Late Warehouse Co"})
        self.env.flush_all()
        self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)]
        ).active = False
        self.env.flush_all()

        picking_type = (
            self.env["stock.picking.type"]
            .with_company(company)
            .create(
                {
                    "name": "Detached",
                    "code": "internal",
                    "sequence_code": "DET",
                    "company_id": company.id,
                    "warehouse_id": False,
                    "default_location_src_id": self.env.ref(
                        "stock.stock_location_suppliers"
                    ).id,
                    "default_location_dest_id": self.env.ref(
                        "stock.stock_location_customers"
                    ).id,
                }
            )
        )
        self.env.flush_all()
        self.assertFalse(picking_type.warehouse_id, "the premise: no warehouse yet")
        self.assertEqual(picking_type.sequence_id.prefix, "DET")

        warehouse = self.env["stock.warehouse"].create(
            {"name": "Late Warehouse", "code": "LWH", "company_id": company.id}
        )
        self.env.flush_all()

        # No `warehouse_id` in this payload. The compute puts one there anyway.
        picking_type.write({"default_location_src_id": warehouse.lot_stock_id.id})
        self.env.flush_all()
        picking_type.invalidate_recordset()

        self.assertEqual(
            picking_type.warehouse_id,
            warehouse,
            "the dependency this module adds is what stages the test",
        )
        self.assertEqual(
            picking_type.sequence_id.prefix,
            picking_type._prepare_sequence_vals()["prefix"],
            "the prefix still describes the warehouse the type has left",
        )
        self.assertEqual(
            picking_type.sequence_id.name,
            picking_type._prepare_sequence_vals()["name"],
        )
