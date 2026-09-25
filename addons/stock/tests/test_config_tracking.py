from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user

CONFIG_MODELS = (
    "stock.warehouse",
    "stock.picking.type",
    "stock.location",
    "stock.route",
    "stock.rule",
    "stock.warehouse.orderpoint",
    "stock.storage.category",
    "stock.putaway.rule",
)

# the stored computes the daily "Procurement: run scheduler" rewrites on every
# reordering rule; tracking one of them would post a message per rule per day
SCHEDULER_REWRITTEN_FIELDS = (
    "qty_to_order_computed",
    "deadline_date",
    "actual_lead_time_avg",
    "actual_lead_time_stddev",
    "lead_time_sample_count",
)

# the mail.tracking.value column pair each tracked field type is stored in
TRACKING_COLUMNS = {
    "boolean": "integer",
    "integer": "integer",
    "float": "float",
    "many2one": "integer",
    "many2many": "char",
    "selection": "char",
}


@tagged("post_install", "-at_install")
class TestConfigTracking(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = mail_new_test_user(
            cls.env,
            login="config_tracking_manager",
            groups="stock.group_stock_manager,stock.group_stock_multi_locations",
        )
        cls.warehouse = cls.env["stock.warehouse"].create(
            {"name": "Tracking Warehouse", "code": "TRKWH"},
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.shelf = cls.env["stock.location"].create(
            {"name": "Tracking Shelf", "location_id": cls.stock_location.id},
        )
        cls.other_shelf = cls.env["stock.location"].create(
            {"name": "Other Tracking Shelf", "location_id": cls.stock_location.id},
        )
        cls.partner = cls.env["res.partner"].create({"name": "Tracking Address"})
        cls.product = cls.env["product.product"].create(
            {"name": "Tracking Product", "type": "consu", "is_storable": True},
        )
        cls.route = cls.env["stock.route"].create(
            {"name": "Tracking Route", "sequence": 5},
        )
        cls.rule = cls.env["stock.rule"].create(
            {
                "name": "Tracking Rule",
                "route_id": cls.route.id,
                "action": "pull",
                "picking_type_id": cls.warehouse.int_type_id.id,
                "location_src_id": cls.stock_location.id,
                "location_dest_id": cls.shelf.id,
            },
        )
        cls.orderpoint = cls.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": cls.product.id,
                "location_id": cls.stock_location.id,
                "trigger": "manual",
                "product_min_qty": 5.0,
                "product_max_qty": 10.0,
            },
        )
        cls.storage_category = cls.env["stock.storage.category"].create(
            {"name": "Tracking Storage"},
        )
        cls.putaway_rule = cls.env["stock.putaway.rule"].create(
            {
                "location_in_id": cls.stock_location.id,
                "location_out_id": cls.shelf.id,
                "product_id": cls.product.id,
            },
        )

    def _flush_tracking(self):
        self.env.flush_all()
        self.env.cr.flush()

    def _write_as_manager(self, record, vals):
        self._flush_tracking()
        before = record.message_ids
        record.with_user(self.manager).write(vals)
        self._flush_tracking()
        return record.message_ids - before

    def _assert_tracked(self, messages, expected):
        """Assert one message by the manager whose tracking values are
        ``expected``, a ``{field: (old, new)}`` map; a relational value is
        compared by id, an x2many by its names."""
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages.author_id, self.manager.partner_id)
        values = messages.sudo().tracking_value_ids.grouped(
            lambda value: value.field_id.name
        )
        self.assertEqual(set(values), set(expected))
        for fname, (old, new) in expected.items():
            with self.subTest(field=fname):
                column = TRACKING_COLUMNS[values[fname].field_id.ttype]
                self.assertEqual(values[fname][f"old_value_{column}"], old)
                self.assertEqual(values[fname][f"new_value_{column}"], new)

    def test_tracked_change_logs_author_and_both_values(self):
        picking_type = self.warehouse.out_type_id
        cases = (
            (
                self.warehouse,
                {"partner_id": self.partner.id},
                {"partner_id": (self.warehouse.partner_id.id, self.partner.id)},
            ),
            (
                picking_type,
                {"show_entire_packs": True, "create_backorder": "never"},
                {"show_entire_packs": (0, 1), "create_backorder": ("Ask", "Never")},
            ),
            (
                picking_type,
                {"wave_location_ids": [Command.set(self.shelf.ids)]},
                {"wave_location_ids": ("", self.shelf.display_name)},
            ),
            (
                self.shelf,
                {"cyclic_inventory_frequency": 30},
                {"cyclic_inventory_frequency": (0, 30)},
            ),
            (
                self.route,
                {"product_selectable": False},
                {"product_selectable": (1, 0)},
            ),
            (self.rule, {"delay": 2}, {"delay": (0, 2)}),
            (
                self.orderpoint,
                {"product_min_qty": 7.0},
                {"product_min_qty": (5.0, 7.0)},
            ),
            (
                self.storage_category,
                {"max_weight": 100.0},
                {"max_weight": (0.0, 100.0)},
            ),
            (
                self.putaway_rule,
                {"location_out_id": self.other_shelf.id},
                {"location_out_id": (self.shelf.id, self.other_shelf.id)},
            ),
        )
        for record, vals, expected in cases:
            with self.subTest(model=record._name, fields=sorted(vals)):
                messages = self._write_as_manager(record, vals)

                self._assert_tracked(messages, expected)

    def test_untracked_or_unchanged_write_logs_nothing(self):
        picking_type = self.warehouse.out_type_id
        cases = (
            (picking_type, {"color": 3}),
            (picking_type, {"active": True}),
            # a list handle rewrites the sequence of every row it moves past
            (self.route, {"sequence": 1}),
            (self.putaway_rule, {"sequence": 3}),
            (self.orderpoint, {"qty_to_order_manual": 4.0}),
            (self.orderpoint, {"snoozed_until": "2099-01-01"}),
            (self.shelf, {"last_inventory_date": "2026-01-01"}),
        )
        for record, vals in cases:
            with self.subTest(model=record._name, fields=sorted(vals)):
                messages = self._write_as_manager(record, vals)

                self.assertFalse(messages)

    def test_scheduler_run_on_reordering_rules_logs_nothing(self):
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        # only auto-triggered rules reach the scheduler's procurement pass
        self.orderpoint.write(
            {
                "trigger": "auto",
                "qty_to_order_manual": 3.0,
                "qty_to_order_manual_set": True,
            },
        )
        demand = self.env["stock.move"].create(
            {
                "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id,
                "product_uom_qty": 3.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        demand._action_confirm()
        self._flush_tracking()
        # a value no computation yields, so its disappearance proves the
        # scheduler rewrote the column; what it rewrites it to depends on
        # whether the installed routes can procure, and does not matter here
        self.env.cr.execute(
            "UPDATE stock_warehouse_orderpoint SET qty_to_order_computed = -1.0"
            " WHERE id = %s",
            [self.orderpoint.id],
        )
        self.env.invalidate_all()
        before = self.orderpoint.message_ids

        self.env["stock.scheduler"].run()
        self.orderpoint.action_remove_manual_qty_to_order()
        self._flush_tracking()

        self.assertNotEqual(self.orderpoint.qty_to_order_computed, -1.0)
        self.assertFalse(self.orderpoint.qty_to_order_manual_set)
        self.assertFalse(self.orderpoint.message_ids - before)
        self.assertFalse(
            set(SCHEDULER_REWRITTEN_FIELDS) & Orderpoint._track_get_fields()
        )

    def test_refused_write_logs_nothing(self):
        self._flush_tracking()
        before = self.orderpoint.message_ids

        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.orderpoint.with_user(self.manager).write(
                {"product_min_qty": 50.0, "product_max_qty": 10.0},
            )
        self._flush_tracking()

        self.assertEqual(self.orderpoint.product_min_qty, 5.0)
        self.assertFalse(self.orderpoint.message_ids - before)

    def test_generated_shortage_rule_is_created_without_log(self):
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        product = self.env["product.product"].create(
            {"name": "Shortage Product", "type": "consu", "is_storable": True},
        )

        generated = self.env["stock.replenishment.report"]._create_shortage_orderpoints(
            {(product.id, self.stock_location.id): -4.0},
            Orderpoint.browse(),
        )
        configured = Orderpoint.with_user(self.manager).create(
            {"product_id": product.id, "location_id": self.shelf.id},
        )
        self._flush_tracking()

        self.assertTrue(generated.is_autogenerated)
        self.assertFalse(generated.message_ids)
        self.assertEqual(len(configured.message_ids), 1)
        self.assertEqual(configured.message_ids.author_id, self.manager.partner_id)

    def test_every_thread_is_read(self):
        # a thread that tracks nothing, or that no form shows, costs a write
        # snapshot per record and answers nobody
        for model in CONFIG_MODELS:
            with self.subTest(model=model):
                arch = self.env[model].get_views([(False, "form")])["views"]["form"][
                    "arch"
                ]

                self.assertTrue(self.env[model]._track_get_fields())
                # exactly one: a second chatter from an inheriting module is
                # the defect marin carried until this change
                self.assertEqual(arch.count("<chatter"), 1)
