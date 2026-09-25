from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestOrderGuards(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.finished, cls.component, cls.byproduct = cls.env["product.product"].create(
            [
                {"name": "Finished", "is_storable": True},
                {"name": "Component", "is_storable": True},
                {"name": "Byproduct", "is_storable": True},
            ]
        )
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 2})
                ],
            }
        )

    def _production(self, qty, bom=None):
        form = Form(self.env["mrp.production"])
        form.product_id = self.finished
        form.bom_id = bom or self.bom
        form.product_qty = qty
        return form.save()

    def _produced(self, qty):
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 100
        )
        production = self._production(qty)
        production.action_confirm()
        production.qty_producing = qty
        production.move_raw_ids.picked = True
        production.button_mark_done()
        return production

    def test_a_done_unbuild_is_not_run_again(self):
        production = self._produced(2)
        unbuild = self.env["mrp.unbuild"].create(
            {"mo_id": production.id, "product_qty": 1}
        )
        unbuild.action_unbuild()
        with self.assertRaises(UserError):
            unbuild.action_unbuild()

    def test_an_unbuild_takes_the_manufacturing_bom_not_the_kit(self):
        self.bom.sequence = 2
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.finished.product_tmpl_id.id,
                "type": "phantom",
                "sequence": 1,
                "bom_line_ids": [
                    Command.create({"product_id": self.component.id, "product_qty": 1})
                ],
            }
        )
        unbuild = self.env["mrp.unbuild"].create(
            {"product_id": self.finished.id, "product_qty": 1}
        )
        self.assertEqual(unbuild.bom_id, self.bom)

    def test_a_second_unbuild_returns_the_serial_the_first_left(self):
        self.component.tracking = "serial"
        self.bom.bom_line_ids.product_qty = 1
        serials = self.env["stock.lot"].create(
            [{"name": name, "product_id": self.component.id} for name in ("S1", "S2")]
        )
        for serial in serials:
            self.env["stock.quant"]._update_available_quantity(
                self.component, self.stock_location, 1, lot_id=serial
            )
        production = self._production(2)
        production.action_confirm()
        production.action_assign()
        production.qty_producing = 2
        production.move_raw_ids.picked = True
        production.button_mark_done()
        unbuilds = self.env["mrp.unbuild"]
        for _index in range(2):
            unbuild = self.env["mrp.unbuild"].create(
                {"mo_id": production.id, "product_qty": 1}
            )
            unbuild.action_unbuild()
            unbuilds |= unbuild
        self.assertEqual(
            sorted(unbuilds.produce_line_ids.move_line_ids.lot_id.mapped("name")),
            ["S1", "S2"],
        )

    def test_a_closed_order_keeps_its_quantity(self):
        production = self._produced(2)
        wizard = self.env["change.production.qty"].create(
            {"mo_id": production.id, "product_qty": 4}
        )
        with self.assertRaises(UserError):
            wizard.change_prod_qty()
        self.assertEqual(production.product_qty, 2)

    def test_a_quantity_change_keeps_a_partial_record(self):
        production = self._production(10)
        production.action_confirm()
        production.qty_producing = 4
        self.env["change.production.qty"].create(
            {"mo_id": production.id, "product_qty": 12}
        ).change_prod_qty()
        self.assertEqual(production.qty_producing, 4)

    def test_a_lowered_quantity_caps_the_partial_record(self):
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 100
        )
        production = self._production(10)
        production.action_confirm()
        production.action_assign()
        with Form(production) as form:
            form.qty_producing = 4
        self.env["change.production.qty"].create(
            {"mo_id": production.id, "product_qty": 3}
        ).change_prod_qty()
        self.assertEqual(production.qty_producing, 3)
        production.button_mark_done()
        self.assertEqual(production.qty_produced, 3)

    def test_a_quantity_change_follows_an_order_producing_all(self):
        production = self._production(10)
        production.action_confirm()
        production.qty_producing = 10
        self.env["change.production.qty"].create(
            {"mo_id": production.id, "product_qty": 12}
        ).change_prod_qty()
        self.assertEqual(production.qty_producing, 12)

    def test_serial_numbers_are_trimmed_and_deduplicated(self):
        self.finished.tracking = "serial"
        production = self._production(2)
        production.action_confirm()
        wizard = self.env["mrp.production.serials"].create(
            {"production_id": production.id, "serial_numbers": "SN1\r\nSN2 \n SN1\n"}
        )
        self.assertEqual(wizard._get_names_from_serial_numbers(), ["SN1", "SN2"])

    def test_a_procured_order_sends_only_its_product_downstream(self):
        self.bom.byproduct_ids = [
            Command.create({"product_id": self.byproduct.id, "product_qty": 1})
        ]
        delivery = self.env["stock.move"].create(
            {
                "product_id": self.finished.id,
                "product_uom_qty": 1,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "procure_method": "make_to_order",
            }
        )
        production = self.env["mrp.production"].create(
            {
                "product_id": self.finished.id,
                "bom_id": self.bom.id,
                "product_qty": 1,
                "move_dest_ids": [Command.link(delivery.id)],
            }
        )
        main = production.move_finished_ids - production.move_byproduct_ids
        self.assertEqual(main.move_dest_ids, delivery)
        self.assertFalse(production.move_byproduct_ids.move_dest_ids)

    def test_orders_created_together_keep_their_own_byproducts(self):
        other, other_byproduct = self.env["product.product"].create(
            [
                {"name": "Other finished", "is_storable": True},
                {"name": "Other byproduct", "is_storable": True},
            ]
        )
        locations = {
            "location_id": self.stock_location.id,
            "location_dest_id": self.stock_location.id,
        }
        productions = self.env["mrp.production"].create(
            [
                {
                    "product_id": product.id,
                    "product_qty": 1,
                    "move_byproduct_ids": [
                        Command.create(
                            {
                                "product_id": byproduct.id,
                                "product_uom_qty": 1,
                                **locations,
                            }
                        )
                    ],
                }
                for product, byproduct in (
                    (self.finished, self.byproduct),
                    (other, other_byproduct),
                )
            ]
        )
        for production, byproduct in zip(
            productions, (self.byproduct, other_byproduct), strict=True
        ):
            self.assertEqual(
                production.move_finished_ids.product_id,
                production.product_id | byproduct,
            )

    def test_unreserving_keeps_the_byproduct_to_produce(self):
        self.bom.byproduct_ids = [
            Command.create({"product_id": self.byproduct.id, "product_qty": 1})
        ]
        self.env["stock.quant"]._update_available_quantity(
            self.component, self.stock_location, 10
        )
        production = self._production(2)
        production.action_confirm()
        production.qty_producing = 2
        production.action_unreserve()
        production.action_assign()
        production.move_raw_ids.picked = True
        production.button_mark_done()
        self.assertEqual(production.move_byproduct_ids.state, "done")
        self.assertEqual(production.move_byproduct_ids.quantity, 2)

    def test_a_bom_unit_change_outdates_its_orders(self):
        production = self._production(1)
        self.assertFalse(production.is_outdated_bom)
        self.bom.product_uom_id = self.uom_dozen
        self.assertTrue(production.is_outdated_bom)

    def test_a_bom_type_change_outdates_its_orders(self):
        production = self._production(1)
        self.assertFalse(production.is_outdated_bom)
        self.bom.type = "phantom"
        self.assertTrue(production.is_outdated_bom)

    def test_an_archived_bom_is_not_counted(self):
        self.bom.byproduct_ids = [
            Command.create({"product_id": self.byproduct.id, "product_qty": 1})
        ]
        self.bom.action_archive()
        self.env.invalidate_all()
        self.assertEqual(self.component.used_in_bom_count, 0)
        self.assertEqual(self.byproduct.bom_count, 0)
        self.assertEqual(self.byproduct.product_tmpl_id.bom_count, 0)

    def test_lead_days_given_no_bom_look_the_bom_up(self):
        self.bom.produce_delay = 5
        rule = self.warehouse_1.manufacture_pull_id
        delays, _descriptions = rule._get_lead_days(
            self.finished, bom=self.env["mrp.bom"]
        )
        self.assertEqual(delays["no_bom_found_delay"], 0)
        self.assertEqual(delays["manufacture_delay"], 5)

    def test_the_settings_form_leaves_orders_alone_until_saved(self):
        production = self._production(1)
        production.action_confirm()
        production.is_locked = False
        form = Form(self.env["res.config.settings"])
        self.assertFalse(production.is_locked, "opening the form re-locked it")
        form.group_unlocked_by_default = True
        form.group_unlocked_by_default = False
        self.assertFalse(production.is_locked, "an unsaved toggle wrote it")
        form.group_mrp_byproducts = not form.group_mrp_byproducts
        form.save().execute()
        self.assertFalse(production.is_locked, "an unrelated save re-locked it")

    def test_unlocking_by_default_applies_on_save(self):
        production = self._production(1)
        production.action_confirm()
        self.assertTrue(production.is_locked)
        self.env["res.config.settings"].create(
            {"group_unlocked_by_default": True}
        ).execute()
        self.assertFalse(production.is_locked)
        self.env["res.config.settings"].create(
            {"group_unlocked_by_default": False}
        ).execute()
        self.assertTrue(production.is_locked)
