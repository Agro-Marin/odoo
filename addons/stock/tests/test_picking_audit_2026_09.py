import importlib.util
import inspect
import pathlib
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.tests import Form, TransactionCase, tagged


class PickingAuditSeptemberCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].create(
            {"name": "Audit September", "code": "AUS"}
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.type_in = cls.warehouse.in_type_id
        cls.type_out = cls.warehouse.out_type_id
        cls.type_int = cls.warehouse.int_type_id
        cls.product = cls.env["product.product"].create(
            {"name": "September audit product", "is_storable": True, "weight": 1.0}
        )
        cls.env["stock.quant"]._update_available_quantity(cls.product, cls.stock, 1000)

    def _picking(self, picking_type, quantity=3.0, **values):
        return self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "move_ids": [
                    Command.create(
                        {"product_id": self.product.id, "product_uom_qty": quantity}
                    )
                ],
                **values,
            }
        )

    def _assigned(self, picking_type, **values):
        picking = self._picking(picking_type, **values)
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _statements(self, function):
        counts = []
        for _attempt in range(2):
            self.env.flush_all()
            self.env.invalidate_all()
            before = self.env.cr.sql_statement_count
            function()
            counts.append(self.env.cr.sql_statement_count - before)
        return counts[-1]


@tagged("post_install", "-at_install")
class TestConfigurationDoesNotRetargetOpenPickings(PickingAuditSeptemberCase):
    def test_a_warehouse_step_change_leaves_open_pickings_where_they_reserved(self):
        receipt = self._assigned(self.type_in)
        delivery = self._assigned(self.type_out)
        self.env.flush_all()

        self.warehouse.write(
            {"reception_steps": "two_steps", "delivery_steps": "pick_ship"}
        )
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertNotEqual(self.type_in.default_location_dest_id, self.stock)
        for record in (receipt, receipt.move_ids, receipt.move_line_ids):
            self.assertEqual(record.location_dest_id, self.stock)
        for record in (delivery, delivery.move_ids, delivery.move_line_ids):
            self.assertEqual(record.location_id, self.stock)

    def test_a_default_change_keeps_a_location_the_user_chose(self):
        shelf = self.env["stock.location"].create(
            {"name": "Chosen shelf", "location_id": self.stock.id}
        )
        other = self.env["stock.location"].create(
            {"name": "New default", "location_id": self.stock.id}
        )
        self.env["stock.quant"]._update_available_quantity(self.product, shelf, 10)
        delivery = self._assigned(self.type_out, location_id=shelf.id)
        self.env.flush_all()

        self.type_out.default_location_src_id = other
        self.env.flush_all()

        self.assertEqual(delivery.location_id, shelf)
        self.assertEqual(delivery.move_ids.location_id, shelf)

    def test_a_partner_location_change_leaves_open_deliveries_alone(self):
        partner = self.env["res.partner"].create({"name": "Relocating customer"})
        delivery = self._assigned(self.type_out, partner_id=partner.id)
        destination = delivery.location_dest_id
        own = self.env["stock.location"].create(
            {
                "name": "Customer own location",
                "usage": "customer",
                "location_id": self.env.ref("stock.stock_location_customers").id,
            }
        )
        self.env.flush_all()

        partner.property_stock_customer = own
        self.env.flush_all()

        for record in (delivery, delivery.move_ids, delivery.move_line_ids):
            self.assertEqual(record.location_dest_id, destination)

    def test_an_empty_draft_picking_still_follows_its_operation_type(self):
        draft = self.env["stock.picking"].create({"picking_type_id": self.type_in.id})
        relocated = self.env["stock.location"].create(
            {"name": "Relocated receipt", "location_id": self.stock.id}
        )
        self.env.flush_all()

        self.type_in.default_location_dest_id = relocated
        self.env.flush_all()

        self.assertEqual(draft.location_dest_id, relocated)

    def test_a_draft_picking_with_moves_keeps_their_locations(self):
        draft = self._picking(self.type_in)
        destination = draft.location_dest_id
        relocated = self.env["stock.location"].create(
            {"name": "Relocated receipt 2", "location_id": self.stock.id}
        )
        self.env.flush_all()

        self.type_in.default_location_dest_id = relocated
        self.env.flush_all()

        for record in (draft, draft.move_ids):
            self.assertEqual(record.location_dest_id, destination)


@tagged("post_install", "-at_install")
class TestPackageHistoryCompany(PickingAuditSeptemberCase):
    def test_the_history_belongs_to_the_company_of_its_transfer(self):
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "History company B"})
        self.env.user.company_ids |= company_b
        env_b = self.env(
            context=dict(self.env.context, allowed_company_ids=[company_b.id])
        )
        warehouse_b = env_b["stock.warehouse"].create(
            {"name": "History B", "code": "HSB", "company_id": company_b.id}
        )
        env_b["stock.quant"]._update_available_quantity(
            self.product, warehouse_b.lot_stock_id, 10
        )
        picking = env_b["stock.picking"].create(
            {
                "picking_type_id": warehouse_b.out_type_id.id,
                "move_ids": [
                    Command.create(
                        {"product_id": self.product.id, "product_uom_qty": 2}
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_line_ids.picked = True
        picking.action_put_in_pack()

        env_ab = self.env(
            context=dict(
                self.env.context, allowed_company_ids=[company_a.id, company_b.id]
            )
        )
        env_ab["stock.picking"].browse(picking.id).button_validate()
        history = self.env["stock.package.history"].search(
            [("picking_ids", "in", picking.ids)]
        )

        self.assertEqual(picking.state, "done")
        self.assertTrue(history)
        self.assertEqual(history.company_id, company_b)

        history.company_id = company_a
        self.env.flush_all()
        migration = importlib.util.spec_from_file_location(
            "stock_post_package_history_company",
            pathlib.Path(__file__).parents[1]
            / "migrations"
            / "1.20"
            / "post-package_history_company.py",
        )
        module = importlib.util.module_from_spec(migration)
        migration.loader.exec_module(module)
        module.migrate(self.env.cr, "1.19")
        history.invalidate_recordset(["company_id"])
        self.assertEqual(history.company_id, company_b)


@tagged("post_install", "-at_install")
class TestShippingPolicyFollowsARealTypeChange(PickingAuditSeptemberCase):
    def test_a_new_picking_takes_the_policy_of_the_type_chosen_in_the_form(self):
        self.type_in.move_type = "direct"
        self.type_out.move_type = "one"
        form = Form(
            self.env["stock.picking"].with_context(
                default_picking_type_id=self.type_in.id
            )
        )
        self.assertEqual(form.move_type, "direct")
        form.picking_type_id = self.type_out
        self.assertEqual(form.move_type, "one")
        self.assertEqual(form.save().move_type, "one")

    def test_a_stored_picking_takes_the_policy_of_its_new_type(self):
        self.type_in.move_type = "direct"
        self.type_int.move_type = "one"
        picking = self.env["stock.picking"].create({"picking_type_id": self.type_in.id})
        self.env.flush_all()

        picking.picking_type_id = self.type_int
        self.env.flush_all()

        self.assertEqual(picking.move_type, "one")

    def test_an_explicit_policy_in_the_same_write_wins(self):
        self.type_int.move_type = "one"
        picking = self.env["stock.picking"].create({"picking_type_id": self.type_in.id})

        picking.write({"picking_type_id": self.type_int.id, "move_type": "direct"})

        self.assertEqual(picking.move_type, "direct")


@tagged("post_install", "-at_install")
class TestBatchWrites(PickingAuditSeptemberCase):
    def _batch(self, *pickings):
        return self.env["stock.picking.batch"].create(
            {
                "picking_type_id": self.type_out.id,
                "picking_ids": [Command.link(picking.id) for picking in pickings],
            }
        )

    def test_several_batches_are_rescheduled_in_one_write(self):
        first = self._picking(self.type_out)
        second = self._picking(self.type_out)
        (first | second).action_confirm()
        batches = self._batch(first) | self._batch(second)
        date_planned = fields.Datetime.now().replace(microsecond=0) + timedelta(days=4)

        batches.write({"date_planned": date_planned})

        self.assertEqual((first | second).mapped("date_planned"), [date_planned] * 2)

    def test_a_cancelled_transfer_does_not_block_rescheduling_its_batch(self):
        open_picking = self._picking(self.type_out)
        cancelled = self._picking(self.type_out)
        (open_picking | cancelled).action_confirm()
        batch = self._batch(open_picking, cancelled)
        cancelled.action_cancel()
        date_planned = fields.Datetime.now().replace(microsecond=0) + timedelta(days=2)

        batch.write({"date_planned": date_planned})

        self.assertEqual(open_picking.date_planned, date_planned)
        self.assertEqual(cancelled.state, "cancel")

    def test_the_batch_responsible_reaches_its_transfers(self):
        picking = self._picking(self.type_out)
        picking.action_confirm()
        batch = self._batch(picking)
        user = self.env["res.users"].create(
            {
                "name": "Batch responsible",
                "login": "audit_batch_responsible",
                "group_ids": [Command.link(self.env.ref("stock.group_stock_user").id)],
            }
        )

        batch.write({"user_id": user.id})

        self.assertEqual(picking.user_id, user)

    def test_validating_a_batch_detaches_its_empty_transfers(self):
        done = self._assigned(self.type_out)
        unstocked = self.env["product.product"].create(
            {"name": "Nothing on hand", "is_storable": True}
        )
        empty = self.env["stock.picking"].create(
            {
                "picking_type_id": self.type_out.id,
                "move_ids": [
                    Command.create({"product_id": unstocked.id, "product_uom_qty": 5})
                ],
            }
        )
        empty.action_confirm()
        batch = self._batch(done, empty)
        batch.action_confirm()
        done.move_ids.picked = True

        batch.action_done()

        self.assertEqual(done.state, "done")
        self.assertFalse(empty.batch_id)
        self.assertEqual(batch.state, "done")


@tagged("post_install", "-at_install")
class TestPackageReadsAreBatched(PickingAuditSeptemberCase):
    def _packed_pickings(self, count):
        pickings = self.env["stock.picking"]
        packages = self.env["stock.package"]
        for index in range(count):
            picking = self._assigned(self.type_out)
            package = self.env["stock.package"].create(
                {"name": f"Batched read {count}-{index}"}
            )
            picking.move_line_ids.result_package_id = package
            pickings |= picking
            packages |= package
        return pickings, packages

    def test_a_package_list_costs_the_same_for_three_or_twelve_rows(self):
        _few_pickings, few = self._packed_pickings(3)
        _many_pickings, many = self._packed_pickings(12)

        def read(packages):
            return self._statements(
                lambda: packages.read(["location_dest_id", "json_popover"])
            )

        self.assertEqual(read(few), read(many))

    def test_counting_packages_costs_the_same_for_three_or_twelve_pickings(self):
        few, _few_packages = self._packed_pickings(3)
        many, _many_packages = self._packed_pickings(12)

        def count(pickings):
            return self._statements(lambda: pickings.mapped("count_packages"))

        self.assertEqual(count(few), count(many))
        self.assertEqual(many.mapped("count_packages"), [1] * 12)

    def _chains(self, count):
        Package = self.env["stock.package"]
        outer = Package.create([{"name": f"Outer {count}-{i}"} for i in range(count)])
        middle = Package.create(
            [
                {"name": f"Middle {count}-{i}", "package_dest_id": package.id}
                for i, package in enumerate(outer)
            ]
        )
        inner = Package.create(
            [
                {"name": f"Inner {count}-{i}", "package_dest_id": package.id}
                for i, package in enumerate(middle)
            ]
        )
        return outer, middle, inner

    def test_walking_nested_destinations_costs_one_read_per_level(self):
        few, *_rest = self._chains(3)
        many, *_rest = self._chains(12)

        def walk(packages):
            return self._statements(packages._get_all_children_package_dest_ids)

        self.assertEqual(walk(few), walk(many))

    def test_the_walk_reports_every_descendant_of_every_root(self):
        outer, middle, inner = self._chains(2)
        roots = outer[0] | middle[0] | outer[1]

        children_by_root, all_ids = roots._get_all_children_package_dest_ids()

        self.assertEqual(set(children_by_root[outer[0]]), {middle[0].id, inner[0].id})
        self.assertEqual(set(children_by_root[middle[0]]), {inner[0].id})
        self.assertEqual(set(children_by_root[outer[1]]), {middle[1].id, inner[1].id})
        self.assertEqual(all_ids, set((outer | middle | inner).ids))

    def test_shipping_weight_weighs_only_the_packages_each_picking_holds(self):
        pickings, _packages = self._packed_pickings(6)
        Package = type(self.env["stock.package"])
        original = Package._get_weight_by_picking
        sizes = []

        def spy(records, *args, **kwargs):
            result = original(records, *args, **kwargs)
            sizes.append(len(result))
            return result

        self.env.invalidate_all()
        with patch.object(Package, "_get_weight_by_picking", spy):
            pickings._fields["shipping_weight"].compute_value(pickings)

        self.assertEqual(sizes, [6])
        self.assertEqual(pickings.mapped("shipping_weight"), [3.0] * 6)


@tagged("post_install", "-at_install")
class TestStoredComputesFollowWhatTheyRead(PickingAuditSeptemberCase):
    def test_a_package_type_weight_reaches_the_shipping_weight(self):
        box = self.env["stock.package.type"].create(
            {"name": "Audit box", "base_weight": 1.0}
        )
        picking = self._assigned(self.type_out, quantity=2)
        picking.move_line_ids.result_package_id = self.env["stock.package"].create(
            {"name": "Weighed box", "package_type_id": box.id}
        )
        self.env.flush_all()
        self.assertEqual(picking.shipping_weight, 3.0)

        box.base_weight = 10.0
        self.env.flush_all()

        self.assertEqual(picking.shipping_weight, 12.0)

    def test_a_wave_location_follows_the_operation_type(self):
        picking = self._assigned(self.type_out)
        batch = self.env["stock.picking.batch"].create(
            {
                "picking_type_id": self.type_out.id,
                "picking_ids": [Command.link(picking.id)],
            }
        )
        self.env.flush_all()
        self.assertFalse(batch.wave_location_id)

        self.type_out.wave_location_ids = [Command.set(self.stock.ids)]
        self.env.flush_all()

        self.assertEqual(batch.wave_location_id, self.stock)


@tagged("post_install", "-at_install")
class TestSmallerPickingDefects(PickingAuditSeptemberCase):
    def test_a_batch_without_an_operation_type_still_offers_allocation(self):
        self.env.user.group_ids = [
            Command.link(self.env.ref("stock.group_reception_report").id)
        ]
        product = self.env["product.product"].create(
            {"name": "Allocated product", "is_storable": True}
        )
        receipt = self.env["stock.picking"].create(
            {
                "picking_type_id": self.type_in.id,
                "move_ids": [
                    Command.create({"product_id": product.id, "product_uom_qty": 5})
                ],
            }
        )
        receipt.action_confirm()
        delivery = self.env["stock.picking"].create(
            {
                "picking_type_id": self.type_out.id,
                "move_ids": [
                    Command.create({"product_id": product.id, "product_uom_qty": 5})
                ],
            }
        )
        delivery.action_confirm()
        batch = self.env["stock.picking.batch"].create(
            {"picking_ids": [Command.link(receipt.id)]}
        )
        batch.picking_type_id = False

        self.assertTrue(receipt.show_allocation)
        self.assertTrue(batch.show_allocation)

    def test_searching_all_children_keeps_a_matched_ancestor(self):
        Package = self.env["stock.package"]
        root = Package.create({"name": "Search root"})
        parent = Package.create({"name": "Search parent", "parent_package_id": root.id})
        child = Package.create({"name": "Search child", "parent_package_id": parent.id})

        found = Package.search(
            [("all_children_package_ids", "in", (parent | child).ids)]
        )

        self.assertEqual(found, root | parent)

    def test_the_sequence_values_depend_on_the_type_alone(self):
        method = type(self.env["stock.picking.type"])._prepare_sequence_vals
        self.assertEqual(list(inspect.signature(method).parameters), ["self"])

    def test_sequence_management_lives_beside_the_type_not_the_dashboard(self):
        for name in (
            "_prepare_sequence_vals",
            "_update_reference_sequences",
            "_remove_orphaned_sequences",
            "_get_clashing_picking_type",
            "_get_unique_sequence_code",
        ):
            owners = [
                klass.__module__
                for klass in type(self.env["stock.picking.type"]).__mro__
                if name in vars(klass)
            ]
            self.assertIn(
                "odoo.addons.stock.models.stock_picking_type_sequence", owners, name
            )
            self.assertNotIn(
                "odoo.addons.stock.models.stock_picking_type_dashboard", owners, name
            )

    def test_the_open_states_are_declared_once(self):
        self.assertFalse(
            hasattr(type(self.env["stock.picking.type"]), "_OPEN_PICKING_STATES")
        )
        late = self._picking(self.type_out)
        late.action_confirm()
        late.date_planned = fields.Datetime.now() - timedelta(days=3)
        self.env.flush_all()
        self.type_out.invalidate_recordset()
        filter_late = self.env["stock.picking"].search_count(
            [
                ("picking_type_id", "=", self.type_out.id),
                ("state", "in", ("assigned", "waiting", "confirmed")),
                "|",
                ("has_deadline_issue", "=", True),
                ("date_category", "in", ["before", "yesterday"]),
            ]
        )
        self.assertEqual(self.type_out.count_picking_late, filter_late)

    def test_the_batch_package_actions_are_the_transfer_actions(self):
        picking = self._assigned(self.type_out)
        batch = self.env["stock.picking.batch"].create(
            {
                "picking_type_id": self.type_out.id,
                "picking_ids": [Command.link(picking.id)],
            }
        )
        self.assertEqual(
            batch.action_view_packages(),
            batch.picking_ids._get_action_view_packages(),
        )
        self.assertEqual(
            batch.action_view_label_layout(),
            batch.picking_ids.action_view_label_type(),
        )
