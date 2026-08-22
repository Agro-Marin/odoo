from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestQuantIncomingDate(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location

    def _tracked_product_with_a_lotless_sibling(self, name, lot_date, loose_date):
        product = self.env["product.product"].create(
            {"name": name, "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": f"{name}-lot", "product_id": product.id}
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, lot_id=lot, in_date=lot_date
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, in_date=loose_date
        )
        self.env.flush_all()
        self.env.invalidate_all()
        return product, lot

    def _lot_quant(self, product, lot):
        return self.Quant.search(
            [
                ("product_id", "=", product.id),
                ("lot_id", "=", lot.id),
                ("location_id", "=", self.loc.id),
            ]
        )

    def test_reserving_does_not_backdate_the_incoming_date(self):
        arrived = datetime(2026, 8, 1)
        product, lot = self._tracked_product_with_a_lotless_sibling(
            "qaud-reserve", arrived, datetime(2019, 1, 1)
        )

        self.Quant._update_reserved_quantity(product, self.loc, 1.0, lot_id=lot)
        self.env.flush_all()
        self.env.invalidate_all()

        quant = self._lot_quant(product, lot)
        self.assertEqual(quant.reserved_quantity, 1.0)
        self.assertEqual(
            quant.in_date,
            arrived,
            "reserving moves no goods, so it must not adopt the lotless "
            "sibling's older in_date",
        )

    def test_a_delivery_reservation_does_not_backdate_the_incoming_date(self):
        arrived = datetime(2026, 8, 1)
        product, lot = self._tracked_product_with_a_lotless_sibling(
            "qaud-delivery", arrived, datetime(2019, 1, 1)
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse_1.out_type_id.id,
                "location_id": self.loc.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": 2,
                            "location_id": self.loc.id,
                            "location_dest_id": self.customer_location.id,
                        },
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(
            self._lot_quant(product, lot).in_date,
            arrived,
            "action_assign must not rewrite in_date -- it is the FIFO sort key",
        )

    def test_reserving_does_not_reorder_removal(self):
        product = self.env["product.product"].create(
            {"name": "qaud-order", "is_storable": True, "tracking": "lot"}
        )
        old, new = self.env["stock.lot"].create(
            [
                {"name": "qaud-order-old", "product_id": product.id},
                {"name": "qaud-order-new", "product_id": product.id},
            ]
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, lot_id=old, in_date=datetime(2021, 1, 1)
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, lot_id=new, in_date=datetime(2026, 1, 1)
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=1, in_date=datetime(2019, 1, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.Quant._gather(product, self.loc).mapped("lot_id.name")

        self.Quant._update_reserved_quantity(product, self.loc, 1.0, lot_id=new)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(
            self.Quant._gather(product, self.loc).mapped("lot_id.name"),
            before,
            "reserving the newest lot must not promote it ahead of the oldest "
            "under FIFO",
        )

    def test_reserving_does_not_age_stock_that_never_moved(self):
        product = self.env["product.product"].create(
            {"name": "qaud-dormant", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qaud-dormant-lot", "product_id": product.id}
        )
        self.Quant._update_available_quantity(product, self.loc, quantity=5, lot_id=lot)
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, in_date=datetime(2019, 1, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        quant = self._lot_quant(product, lot)
        self.assertFalse(quant.date_last_movement)
        self.assertEqual(quant.days_since_last_movement, 0)

        self.Quant._update_reserved_quantity(product, self.loc, 1.0, lot_id=lot)
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(
            self._lot_quant(product, lot).days_since_last_movement,
            0,
            "a reservation is not seven years of standing still",
        )

    def test_receiving_still_merges_to_the_oldest_incoming_date(self):
        product = self.env["product.product"].create(
            {"name": "qaud-merge", "is_storable": True}
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, in_date=datetime(2026, 8, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        self.Quant._update_available_quantity(
            product, self.loc, quantity=3, in_date=datetime(2019, 1, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        quant = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", self.loc.id)]
        )
        self.assertEqual(quant.quantity, 8)
        self.assertEqual(
            quant.in_date,
            datetime(2019, 1, 1),
            "an incoming quantity still carries the oldest in_date of its group",
        )


@tagged("post_install", "-at_install")
class TestQuantCreateContract(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location
        cls.env.user.group_ids = [
            (4, cls.env.ref("stock.group_stock_user").id),
            (4, cls.env.ref("stock.group_stock_manager").id),
        ]

    def test_create_returns_one_record_per_vals(self):
        product = self.env["product.product"].create(
            {"name": "qaud-contract", "is_storable": True}
        )
        vals_list = [
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 3,
            },
            {
                "product_id": product.id,
                "location_id": self.env["stock.location"]
                .create(
                    {
                        "name": "qaud-contract-loc",
                        "usage": "internal",
                        "location_id": self.loc.id,
                    }
                )
                .id,
                "inventory_quantity": 4,
            },
        ]
        quants = self.Quant.with_context(inventory_mode=True).create(vals_list)
        self.assertEqual(
            len(quants),
            len(vals_list),
            "create() must return one record per vals, positionally aligned",
        )

    def test_two_counted_lines_for_one_quant_are_refused(self):
        product = self.env["product.product"].create(
            {"name": "qaud-dup", "is_storable": True}
        )
        vals_list = [
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 3,
            },
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 4,
            },
        ]
        with self.assertRaises(UserError):
            self.Quant.with_context(inventory_mode=True).create(vals_list)

    def test_a_data_file_collision_names_itself(self):
        product = self.env["product.product"].create(
            {"name": "qaud-load", "is_storable": True}
        )
        data = [
            {
                "xml_id": "stock.qaud_load_a",
                "values": {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "inventory_quantity": 3,
                },
            },
            {
                "xml_id": "stock.qaud_load_b",
                "values": {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "inventory_quantity": 4,
                },
            },
        ]
        with self.assertRaises(UserError):
            self.Quant._load_records(data)

    def test_the_web_importer_still_creates_a_row_per_line(self):
        product = self.env["product.product"].create(
            {"name": "qaud-import", "is_storable": True}
        )
        vals_list = [
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 3,
            },
            {
                "product_id": product.id,
                "location_id": self.loc.id,
                "inventory_quantity": 4,
            },
        ]
        quants = self.Quant.with_context(inventory_mode=True, import_file=True).create(
            vals_list
        )
        self.assertEqual(len(quants), 2)

    def test_name_create_refuses_with_a_reason(self):
        with self.assertRaises(UserError):
            self.env["stock.quant"].name_create("anything")


@tagged("post_install", "-at_install")
class TestQuantExpirationBoundary(TestStockCommon):
    def test_stock_never_names_a_product_expiry_field(self):
        import inspect

        from odoo.addons.stock.models import stock_quant

        source = inspect.getsource(stock_quant)
        self.assertNotIn(
            "removal_date",
            source,
            "stock/models/stock_quant.py must reach expiry through "
            "_get_expiration_domain / _filtered_not_expired, not by name",
        )

    def test_the_base_hooks_are_neutral(self):
        quant = self.env["stock.quant"]
        self.assertEqual(quant._get_expiration_domain(), Domain.TRUE)
        product = self.env["product.product"].create(
            {"name": "qaud-expiry", "is_storable": True}
        )
        quant._update_available_quantity(product, self.stock_location, quantity=1)
        self.env.flush_all()
        quants = quant.search([("product_id", "=", product.id)])
        self.assertEqual(quants._filtered_not_expired(), quants)


@tagged("post_install", "-at_install")
class TestQuantSweepShape(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location

    def _drift(self, count, tag):
        products = self.env["product.product"].create(
            [
                {"name": f"qaud-{tag}-{index}", "is_storable": True}
                for index in range(count)
            ]
        )
        for product in products:
            self.Quant._update_available_quantity(product, self.loc, quantity=10)
            self.Quant._update_available_quantity(
                product, self.loc, reserved_quantity=3
            )
        self.env.flush_all()
        self.env.invalidate_all()
        return products

    def _clean_cost(self, products):
        before = self.env.cr.sql_log_count
        self.Quant._clean_reservations(products=products, locations=self.loc)
        self.env.flush_all()
        return self.env.cr.sql_log_count - before

    def test_clean_reservations_cost_per_group_is_bounded(self):
        small = self._clean_cost(self._drift(2, "small"))
        large = self._clean_cost(self._drift(20, "large"))
        marginal = (large - small) / 18
        self.assertLessEqual(
            marginal,
            2.5,
            "correcting one drifted group must not re-gather the quants the "
            f"read_group already returned (measured {marginal:.1f} queries/group)",
        )

    def test_clean_reservations_still_corrects_the_drift(self):
        products = self._drift(3, "correct")
        self.Quant._clean_reservations(products=products, locations=self.loc)
        self.env.flush_all()
        self.env.invalidate_all()
        quants = self.Quant.search(
            [("product_id", "in", products.ids), ("location_id", "=", self.loc.id)]
        )
        self.assertEqual(
            sum(quants.mapped("reserved_quantity")),
            0,
            "a reservation with no move line behind it is dropped",
        )

    def test_clean_reservations_leaves_the_incoming_date_alone(self):
        product = self.env["product.product"].create(
            {"name": "qaud-clean-date", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qaud-clean-lot", "product_id": product.id}
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, lot_id=lot, in_date=datetime(2026, 8, 1)
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=5, in_date=datetime(2019, 1, 1)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        self.Quant.search(
            [("product_id", "=", product.id), ("lot_id", "=", lot.id)]
        ).sudo().write({"reserved_quantity": 2})
        self.env.flush_all()
        self.env.invalidate_all()

        self.Quant._clean_reservations(products=product, locations=self.loc)
        self.env.flush_all()
        self.env.invalidate_all()

        quant = self.Quant.search(
            [
                ("product_id", "=", product.id),
                ("lot_id", "=", lot.id),
                ("location_id", "=", self.loc.id),
            ]
        )
        self.assertEqual(quant.in_date, datetime(2026, 8, 1))


@tagged("post_install", "-at_install")
class TestQuantSearchShape(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location

    def test_dormancy_search_does_not_materialise_every_id(self):
        product = self.env["product.product"].create(
            {"name": "qaud-subq", "is_storable": True}
        )
        self.Quant._update_available_quantity(
            product,
            self.loc,
            quantity=5,
            in_date=datetime.now() - timedelta(days=400),
        )
        self.env.flush_all()
        for operator, value in ((">=", 100), ("<", 100)):
            domain = self.Quant._search_days_since_last_movement(operator, value)
            self.assertFalse(
                isinstance(domain[0][2], list),
                "the dormancy search must hand the planner a subquery, not one "
                "id per dormant quant in the database",
            )

    def test_is_outdated_search_does_not_materialise_every_id(self):
        domain = self.Quant._search_is_outdated("in", [True])
        self.assertFalse(isinstance(domain[0][2], list))

    def test_dormancy_search_still_matches_the_compute(self):
        product = self.env["product.product"].create(
            {"name": "qaud-agree", "is_storable": True}
        )
        for days in (5, 400):
            location = self.env["stock.location"].create(
                {
                    "name": f"qaud-agree-{days}",
                    "usage": "internal",
                    "location_id": self.loc.id,
                }
            )
            self.Quant._update_available_quantity(
                product,
                location,
                quantity=5,
                in_date=datetime.now() - timedelta(days=days),
            )
        self.env.flush_all()
        self.env.invalidate_all()
        quants = self.Quant.search([("product_id", "=", product.id)])
        checks = {
            ">=": lambda days, t: days >= t,
            ">": lambda days, t: days > t,
            "<": lambda days, t: days < t,
            "<=": lambda days, t: days <= t,
        }
        for threshold in (10, 100, 500):
            for operator, predicate in checks.items():
                found = self.Quant.search(
                    [
                        ("product_id", "=", product.id),
                        ("days_since_last_movement", operator, threshold),
                    ]
                )
                expected = quants.filtered(
                    lambda q, t=threshold, f=predicate: f(q.days_since_last_movement, t)
                )
                self.assertEqual(
                    set(found.ids),
                    set(expected.ids),
                    f"search and compute must agree on {operator} {threshold}; "
                    "the '<' and '<=' branches are the negated-subquery path",
                )

    def test_the_zero_sweep_keeps_its_rounding_tolerance(self):
        product = self.env["product.product"].create(
            {"name": "qaud-eps", "is_storable": True}
        )
        quant = self.Quant.create(
            {"product_id": product.id, "location_id": self.loc.id, "quantity": 0}
        )
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE stock_quant SET quantity = 1e-9 WHERE id = %s", [quant.id]
        )
        self.env.invalidate_all()
        self.Quant._unlink_zero_quants(products=product, locations=self.loc)
        self.assertFalse(
            quant.exists(),
            "a residue below the rounding precision is still a zero quant",
        )

    def test_the_zero_sweep_keeps_real_stock(self):
        product = self.env["product.product"].create(
            {"name": "qaud-eps-keep", "is_storable": True}
        )
        quant = self.Quant.create(
            {"product_id": product.id, "location_id": self.loc.id, "quantity": 0.01}
        )
        self.env.flush_all()
        self.Quant._unlink_zero_quants(products=product, locations=self.loc)
        self.assertTrue(quant.exists())


@tagged("post_install", "-at_install")
class TestQuantActionDomain(TestStockCommon):
    def test_the_quants_action_keeps_the_action_domain(self):
        action = self.env.ref("stock.stock_quant_action").sudo()
        action.domain = "[('quantity', '>', 0)]"
        self.env.flush_all()
        built = (
            self.env["stock.quant"]
            .with_context(skip_quant_tasks=True)
            ._get_quants_action()
        )
        conditions = [
            (condition.field_expr, condition.operator, condition.value)
            for condition in Domain(built["domain"]).iter_conditions()
        ]
        self.assertIn(
            ("quantity", ">", 0),
            conditions,
            "the company narrowing must be added to the action's domain, not "
            "written over it",
        )
        self.assertIn(
            "product_id.company_id",
            [field for field, _operator, _value in conditions],
        )


@tagged("post_install", "-at_install")
class TestQuantFormLookups(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.loc = cls.stock_location

    def test_dropping_the_lot_reads_the_on_hand_without_it(self):
        untracked = self.env["product.product"].create(
            {"name": "qaud-form-untracked", "is_storable": True}
        )
        tracked = self.env["product.product"].create(
            {"name": "qaud-form-tracked", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qaud-form-lot", "product_id": tracked.id}
        )
        self.Quant._update_available_quantity(tracked, self.loc, quantity=7, lot_id=lot)
        self.Quant._update_available_quantity(untracked, self.loc, quantity=3)
        self.env.flush_all()
        self.env.invalidate_all()

        form = self.Quant.new(
            {
                "location_id": self.loc.id,
                "product_id": untracked.id,
                "lot_id": lot.id,
            }
        )
        form._onchange_location_or_product_id()

        self.assertFalse(form.lot_id, "a lot of another product must be dropped")
        self.assertEqual(
            form.quantity,
            3.0,
            "the on hand must be read for the identity the form ends up with, "
            "not for the lot that was just removed",
        )

    def test_keeping_the_lot_still_reads_that_lot(self):
        tracked = self.env["product.product"].create(
            {"name": "qaud-form-keep", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qaud-form-keep-lot", "product_id": tracked.id}
        )
        self.Quant._update_available_quantity(tracked, self.loc, quantity=7, lot_id=lot)
        self.Quant._update_available_quantity(tracked, self.loc, quantity=99)
        self.env.flush_all()
        self.env.invalidate_all()

        form = self.Quant.new(
            {
                "location_id": self.loc.id,
                "product_id": tracked.id,
                "lot_id": lot.id,
            }
        )
        form._onchange_location_or_product_id()
        self.assertEqual(form.lot_id, lot)
        self.assertEqual(
            form.quantity,
            7.0,
            "a kept lot reads its own quantity, not the untracked stock beside it",
        )

    def test_history_is_scoped_to_the_quant_owner(self):
        owner = self.env["res.partner"].create({"name": "qaud-history-owner"})
        product = self.env["product.product"].create(
            {"name": "qaud-history", "is_storable": True}
        )
        self.Quant._update_available_quantity(
            product, self.loc, quantity=4, owner_id=owner
        )
        self.env.flush_all()
        quant = self.Quant.search(
            [("product_id", "=", product.id), ("owner_id", "=", owner.id)]
        )
        action = quant.action_view_stock_moves()
        conditions = {
            condition.field_expr
            for condition in Domain(action["domain"]).iter_conditions()
        }
        self.assertIn(
            "owner_id",
            conditions,
            "owner_id is part of the quant's identity in _move_line_match_key and "
            "_reservation_key; history cannot be the one place it is dropped",
        )

    def test_the_constraint_methods_are_named_and_scoped_as_constraints(self):
        model = type(self.env["stock.quant"])
        for name in ("_check_location_id", "_check_product_id", "_check_lot_id"):
            self.assertTrue(
                hasattr(model, name), f"{name} must exist under the §2.4 spelling"
            )
        for name in ("check_location_id", "check_product_id", "check_lot_id"):
            self.assertFalse(
                hasattr(model, name),
                f"{name} must not survive as a public alias -- a public method is "
                "callable over RPC",
            )
        constrained = {
            method.__name__ for method in self.env["stock.quant"]._constraint_methods
        }
        for name in ("_check_location_id", "_check_product_id", "_check_lot_id"):
            self.assertIn(
                name, constrained, f"{name} must still be registered as a constraint"
            )


@tagged("post_install", "-at_install")
class TestQuantRelocateWizard(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.Wizard = cls.env["stock.quant.relocate"]
        cls.loc = cls.stock_location

    def _packed_quants(self, tag, packages, per_package):
        product = self.env["product.product"].create(
            {"name": f"qrel-{tag}", "is_storable": True, "tracking": "lot"}
        )
        lots = self.env["stock.lot"].create(
            [
                {"name": f"qrel-{tag}-l{index}", "product_id": product.id}
                for index in range(per_package)
            ]
        )
        pkgs = self.env["stock.package"].create(
            [{"name": f"qrel-{tag}-p{index}"} for index in range(packages)]
        )
        self.Quant.create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "lot_id": lot.id,
                    "package_id": package.id,
                    "quantity": 1.0,
                }
                for package in pkgs
                for lot in lots
            ]
        )
        self.env.flush_all()
        return pkgs

    def test_a_whole_package_selection_is_not_partial(self):
        pkgs = self._packed_quants("whole", packages=2, per_package=3)
        wizard = self.Wizard.create({"quant_ids": [(6, 0, pkgs.quant_ids.ids)]})
        self.assertFalse(wizard.is_partial_package)
        self.assertFalse(wizard.partial_package_names)

    def test_a_partial_package_is_named(self):
        pkgs = self._packed_quants("partial", packages=2, per_package=3)
        selection = pkgs[0].quant_ids[:2] | pkgs[1].quant_ids
        wizard = self.Wizard.create({"quant_ids": [(6, 0, selection.ids)]})
        self.assertTrue(wizard.is_partial_package)
        self.assertEqual(wizard.partial_package_names, pkgs[0].display_name)

    def test_loose_quants_are_never_partial(self):
        product = self.env["product.product"].create(
            {"name": "qrel-loose", "is_storable": True}
        )
        self.Quant._update_available_quantity(product, self.loc, quantity=5)
        self.env.flush_all()
        quants = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", self.loc.id)]
        )
        wizard = self.Wizard.create({"quant_ids": [(6, 0, quants.ids)]})
        self.assertFalse(
            wizard.is_partial_package, "stock in no package breaks no package open"
        )

    def test_the_partial_package_answer_does_not_cost_the_square_of_the_selection(self):
        import time

        def measure(tag, packages, per_package):
            pkgs = self._packed_quants(tag, packages, per_package)
            wizard = self.Wizard.create({"quant_ids": [(6, 0, pkgs.quant_ids.ids)]})
            self.env.flush_all()
            wizard.quant_ids.mapped("package_id.quant_ids")
            wizard.invalidate_recordset(["is_partial_package", "partial_package_names"])
            started = time.perf_counter()
            _ = wizard.is_partial_package
            return time.perf_counter() - started

        small = measure("small", packages=4, per_package=25)
        large = measure("large", packages=40, per_package=25)
        self.assertLess(
            large,
            max(small, 1e-4) * 25,
            f"a 10x selection cost {large / max(small, 1e-9):.0f}x the time; the "
            "membership set has to be hoisted out of the filter",
        )

    def test_a_lot_keeps_the_packages_it_owns_outright(self):
        product = self.env["product.product"].create(
            {"name": "qrel-lot-own", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qrel-lot-own-l", "product_id": product.id}
        )
        first, second = self.env["stock.package"].create(
            [{"name": "qrel-own-a"}, {"name": "qrel-own-b"}]
        )
        for package in (first, second):
            self.Quant._update_available_quantity(
                product, self.loc, quantity=1, lot_id=lot, package_id=package
            )
        self.env.flush_all()
        destination = self.env["stock.location"].create(
            {
                "name": "qrel-own-dest",
                "usage": "internal",
                "location_id": self.loc.id,
            }
        )

        lot.location_id = destination
        self.env.flush_all()
        self.env.invalidate_all()

        moved = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", destination.id)]
        )
        self.assertEqual(sum(moved.mapped("quantity")), 2.0)
        self.assertEqual(
            moved.package_id,
            first | second,
            "both packages held nothing but this lot, so both travel intact",
        )

    def test_a_lot_leaves_a_package_it_shares(self):
        product = self.env["product.product"].create(
            {"name": "qrel-lot-share", "is_storable": True, "tracking": "lot"}
        )
        neighbour = self.env["product.product"].create(
            {"name": "qrel-lot-share-n", "is_storable": True}
        )
        lot = self.env["stock.lot"].create(
            {"name": "qrel-lot-share-l", "product_id": product.id}
        )
        package = self.env["stock.package"].create({"name": "qrel-share"})
        self.Quant._update_available_quantity(
            product, self.loc, quantity=1, lot_id=lot, package_id=package
        )
        self.Quant._update_available_quantity(
            neighbour, self.loc, quantity=1, package_id=package
        )
        self.env.flush_all()
        destination = self.env["stock.location"].create(
            {
                "name": "qrel-share-dest",
                "usage": "internal",
                "location_id": self.loc.id,
            }
        )

        lot.location_id = destination
        self.env.flush_all()
        self.env.invalidate_all()

        moved = self.Quant.search(
            [("product_id", "=", product.id), ("location_id", "=", destination.id)]
        )
        self.assertEqual(sum(moved.mapped("quantity")), 1.0)
        self.assertFalse(
            moved.package_id,
            "the package stays behind with the neighbour that was not moved",
        )

    def test_the_predicate_has_one_definition(self):
        import inspect

        from odoo.addons.stock.models import stock_lot
        from odoo.addons.stock.wizard import stock_quant_relocate

        for module in (stock_lot, stock_quant_relocate):
            source = inspect.getsource(module)
            self.assertIn("_filtered_breaking_a_package", source)
            self.assertNotIn(
                "package_id.quant_ids)",
                source,
                f"{module.__name__} must reach the package-completeness test "
                "through stock.quant, not re-spell it",
            )
