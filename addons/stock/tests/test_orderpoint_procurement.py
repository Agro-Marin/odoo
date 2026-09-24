from datetime import datetime, timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrderpointProcurement(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Orderpoint = cls.env["stock.warehouse.orderpoint"]
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customers = cls.env.ref("stock.stock_location_customers")

    def _product(self, name, **values):
        return self.env["product.product"].create(
            {"name": name, "is_storable": True, **values},
        )

    def _orderpoint(self, product, **overrides):
        return self.Orderpoint.create(
            {
                "product_id": product.id,
                "product_min_qty": 5,
                "product_max_qty": 10,
                "trigger": "manual",
                **overrides,
            },
        )

    def _move(self, product, quantity, source, destination, days_out):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": quantity,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "date": fields.Datetime.now() + timedelta(days=days_out),
            },
        )
        move._action_confirm()
        return move

    def _unsuppliable_location(self, name):
        root = self.env["stock.location"].create(
            {"name": f"{name} Root", "usage": "view", "location_id": False},
        )
        return self.env["stock.location"].create(
            {"name": name, "usage": "internal", "location_id": root.id},
        )

    def _statements(self, function):
        before = self.env.cr.sql_statement_count
        function()
        return self.env.cr.sql_statement_count - before

    def test_the_to_reorder_filter_follows_the_report_horizon(self):
        self.env.company.stock_config_id.horizon_days = 0
        product = self._product("Horizon Filter")
        self._move(product, 8, self.stock_location, self.customers, 10)
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock_location, 10
        )
        orderpoint = self._orderpoint(product)
        self.env.flush_all()
        widened = self.Orderpoint.with_context(global_horizon_days=15)
        self.assertEqual(
            orderpoint.with_context(global_horizon_days=15).qty_to_order, 8
        )
        self.assertEqual(
            widened.search([("id", "=", orderpoint.id), ("qty_to_order", ">", 0)]),
            orderpoint,
            "a row the widened horizon gives something to order must pass the filter",
        )
        self.assertFalse(
            self.Orderpoint.search(
                [("id", "=", orderpoint.id), ("qty_to_order", ">", 0)],
            ),
        )

        self.env.company.stock_config_id.horizon_days = 365
        self.env.flush_all()
        narrowed = self.Orderpoint.with_context(global_horizon_days=5)
        self.assertEqual(orderpoint.with_context(global_horizon_days=5).qty_to_order, 0)
        self.assertFalse(
            narrowed.search([("id", "=", orderpoint.id), ("qty_to_order", ">", 0)]),
            "a row showing nothing to order must not pass the filter",
        )

    def test_a_widened_horizon_keeps_the_report_suggestion(self):
        self.env.company.stock_config_id.horizon_days = 0
        product = self._product("Horizon Churn")
        self._move(product, 8, self.stock_location, self.customers, 10)
        self.env.flush_all()
        Orderpoint = self.Orderpoint.with_context(global_horizon_days=15)
        Orderpoint.action_view_orderpoints()
        first = self.Orderpoint.search([("product_id", "=", product.id)])
        self.assertEqual(len(first), 1)
        first.snoozed_until = fields.Date.today() + timedelta(days=3)
        Orderpoint.action_view_orderpoints()
        self.assertTrue(
            first.exists(),
            "reopening the report under the same horizon must not recreate the row",
        )
        self.assertEqual(
            self.Orderpoint.search([("product_id", "=", product.id)]),
            first,
        )

    def test_a_deadline_does_not_depend_on_the_batch(self):
        shelf = self.env["stock.location"].create(
            {"name": "Pickface", "location_id": self.stock_location.id},
        )
        product = self._product("Deadline Batch")
        Quant = self.env["stock.quant"]
        Quant._update_available_quantity(product, self.stock_location, 100)
        Quant._update_available_quantity(product, shelf, 10)
        self._move(product, 20, self.stock_location, shelf, 2)
        self._move(product, 15, shelf, self.customers, 5)
        bulk = self._orderpoint(
            product,
            location_id=self.stock_location.id,
            product_min_qty=10,
            product_max_qty=200,
        )
        face = self._orderpoint(
            product,
            location_id=shelf.id,
            product_min_qty=5,
            product_max_qty=30,
        )
        self.env.flush_all()
        face._update_stored_values()
        alone = face.deadline_date
        (bulk | face)._update_stored_values()
        self.assertEqual(face.deadline_date, alone)
        self.assertFalse(
            face.deadline_date,
            "the replenishment from bulk stock arrives before the delivery",
        )

    def test_a_deadline_sees_a_move_between_two_orderpoint_locations(self):
        other = self.env["stock.warehouse"].create({"name": "Audit Two", "code": "AT2"})
        product = self._product("Deadline Transfer")
        Quant = self.env["stock.quant"]
        Quant._update_available_quantity(product, self.stock_location, 50)
        Quant._update_available_quantity(product, other.lot_stock_id, 50)
        move = self._move(product, 45, self.stock_location, other.lot_stock_id, 3)
        source = self._orderpoint(product, product_min_qty=10, product_max_qty=20)
        self._orderpoint(
            product,
            warehouse_id=other.id,
            location_id=other.lot_stock_id.id,
            product_min_qty=10,
            product_max_qty=20,
        )
        self.env.flush_all()
        self.Orderpoint.search(
            [("product_id", "=", product.id)]
        )._update_stored_values()
        self.assertEqual(source.deadline_date, move.date.date())

    def test_preparing_procurements_does_not_scale_with_orderpoints(self):
        def prepare(count):
            products = self.env["product.product"].create(
                [
                    {"name": f"Scale {count} {index}", "is_storable": True}
                    for index in range(count)
                ],
            )
            orderpoints = self.Orderpoint.create(
                [
                    {
                        "product_id": product.id,
                        "product_min_qty": 5,
                        "product_max_qty": 10,
                    }
                    for product in products
                ],
            )
            self.env.flush_all()
            self.env.invalidate_all()
            orderpoints = orderpoints.browse(orderpoints.ids)
            procurements = []
            statements = self._statements(
                lambda: procurements.extend(orderpoints._prepare_procurements({})),
            )
            self.assertEqual(len(procurements), count)
            return statements

        prepare(2)
        self.assertEqual(prepare(9), prepare(3))

    def test_a_failing_orderpoint_does_not_abort_the_batch(self):
        products = self.env["product.product"].create(
            [{"name": f"Batch {index}", "is_storable": True} for index in range(5)],
        )
        orderpoints = self.Orderpoint.create(
            [
                {"product_id": product.id, "product_min_qty": 5, "trigger": "auto"}
                for product in products
            ],
        )
        poison = products[2]
        self.env.flush_all()
        Rule = type(self.env["stock.rule"])
        prepare = Rule._prepare_stock_move_vals

        def failing(rule, procurement):
            if procurement.product_id == poison:
                raise ValidationError("Audit: simulated constraint")
            return prepare(rule, procurement)

        with patch.object(Rule, "_prepare_stock_move_vals", failing):
            failures = orderpoints._run_procurement_batch({}, raise_user_error=False)
        self.assertEqual(
            [(orderpoint.product_id, message) for orderpoint, message in failures],
            [(poison, "Audit: simulated constraint")],
        )
        self.assertEqual(
            set(
                self.env["stock.move"]
                .search([("orderpoint_id", "in", orderpoints.ids)])
                .product_id.ids
            ),
            set((products - poison).ids),
        )
        with (
            patch.object(Rule, "_prepare_stock_move_vals", failing),
            self.assertRaises(ValidationError),
        ):
            orderpoints._run_procurement_batch({}, raise_user_error=True)

    def test_an_unattributed_failure_is_isolated(self):
        good = self._product("Unattributed Good")
        bad = self._product("Unattributed Bad")
        orderpoints = self._orderpoint(good) + self._orderpoint(
            bad,
            location_id=self._unsuppliable_location("Unattributed Nowhere").id,
        )
        self.env.flush_all()
        failures = orderpoints._run_procurement_batch({}, raise_user_error=False)
        self.assertEqual(
            [orderpoint.product_id for orderpoint, _msg in failures], [bad]
        )
        self.assertTrue(
            self.env["stock.move"].search_count([("product_id", "=", good.id)]),
            "a manual orderpoint's failure must not roll back its neighbours",
        )

    def test_orderpoint_dates_follow_the_company_timezone(self):
        self.env.company.partner_id.tz = "America/Mexico_City"
        self.env.company.stock_config_id.horizon_days = 0
        product = self._product("Timezone")
        orderpoint = self._orderpoint(product, trigger="auto")
        self.env.flush_all()
        with freeze_time("2026-09-24 02:00:00"):
            self.env.invalidate_all()
            self.assertEqual(
                orderpoint.lead_horizon_date,
                fields.Date.to_date("2026-09-23"),
            )
            procurement = orderpoint._prepare_procurements({})[0]
            self.assertEqual(
                procurement.values["date_planned"],
                datetime(2026, 9, 23, 18, 0),
                "local noon of the company's today, not of the UTC date",
            )
            orderpoint._update_stored_values()
            self.assertEqual(
                orderpoint.deadline_date,
                fields.Date.to_date("2026-09-23"),
            )

    def test_a_procurement_without_warehouse_is_resolved(self):
        product = self._product("No Warehouse")
        Rule = self.env["stock.rule"]
        self.assertEqual(
            Rule._get_rule(product, self.stock_location, {"warehouse_id": False}),
            Rule._get_rule(
                product,
                self.stock_location,
                {"warehouse_id": self.env["stock.warehouse"]},
            ),
        )
        procurement = Rule.Procurement(
            product,
            1,
            product.uom_id,
            self.stock_location,
            "Audit",
            "Audit",
            self.env.company,
            {"warehouse_id": False, "route_ids": self.warehouse.reception_route_id},
        )
        Rule.run([procurement])
        self.assertTrue(
            self.env["stock.move"].search_count([("product_id", "=", product.id)]),
        )

    def test_the_default_route_reads_parent_categories(self):
        route = self.warehouse.reception_route_id
        parent = self.env["product.category"].create(
            {"name": "Audit Parent", "route_ids": [Command.set(route.ids)]},
        )
        child = self.env["product.category"].create(
            {"name": "Audit Child", "parent_id": parent.id},
        )
        orderpoint = self._orderpoint(self._product("Child Route", categ_id=child.id))
        self.assertEqual(orderpoint.effective_route_id, route)
        self.assertEqual(orderpoint.route_id_placeholder, route.display_name)
        self.assertEqual(
            self.Orderpoint.search(
                [("id", "=", orderpoint.id), ("effective_route_id", "in", route.ids)],
            ),
            orderpoint,
        )

    def test_the_shortage_netting_does_not_compute_suggestions(self):
        product = self._product("Netting")
        self._move(product, 8, self.stock_location, self.customers, 1)
        self._orderpoint(product)
        self.env.flush_all()
        self.env.invalidate_all()
        Orderpoint = type(self.Orderpoint)
        compute = Orderpoint._compute_qty_to_order
        calls = []

        def counting(records):
            calls.append(records)
            return compute(records)

        report = self.env["stock.replenishment.report"]
        shortages = report._get_projected_shortages()
        with patch.object(Orderpoint, "_compute_qty_to_order", counting):
            report._get_net_shortages(shortages)
        self.assertFalse(calls)

    def test_the_replenish_wizard_routes_follow_its_warehouse(self):
        other = self.env["stock.warehouse"].create({"name": "Audit Wiz", "code": "AWZ"})
        product = self._product("Wizard Route")
        Route = type(self.env["stock.route"])
        with patch.object(
            Route,
            "_is_valid_resupply_route_for_product",
            lambda route, product: True,
        ):
            wizard = self.env["product.replenish"].new(
                {
                    "product_id": product.id,
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "product_uom_id": product.uom_id.id,
                    "warehouse_id": self.warehouse.id,
                },
            )
            self.assertIn(
                self.warehouse.reception_route_id, wizard.allowed_route_ids._origin
            )
            self.assertNotIn(other.reception_route_id, wizard.allowed_route_ids._origin)
            wizard.warehouse_id = other
            self.assertIn(other.reception_route_id, wizard.allowed_route_ids._origin)

    def test_a_resupply_leg_is_renamed_with_its_source(self):
        supplier = self.env["stock.warehouse"].create(
            {"name": "Audit Sup", "code": "ASP"}
        )
        self.env["stock.warehouse"].create(
            {
                "name": "Audit Dem",
                "code": "ADM",
                "resupply_wh_ids": [Command.set(supplier.ids)],
            },
        )
        supplier.delivery_steps = "pick_ship"
        leg = self.env["stock.rule"].search(
            [
                ("route_id.supplier_wh_id", "=", supplier.id),
                ("location_dest_id.usage", "=", "transit"),
            ],
        )
        self.assertEqual(leg.location_src_id, supplier.wh_output_stock_loc_id)
        self.assertEqual(
            leg.name,
            supplier._format_rulename(leg.location_src_id, leg.location_dest_id, ""),
        )

    def test_the_scheduler_refreshes_orderpoints_in_batches(self):
        products = self.env["product.product"].create(
            [{"name": f"Refresh {index}", "is_storable": True} for index in range(5)],
        )
        self.Orderpoint.create(
            [{"product_id": product.id, "product_min_qty": 1} for product in products],
        )
        self.env.flush_all()
        Orderpoint = type(self.Orderpoint)
        update = Orderpoint._update_stored_values
        sizes = []

        def recording(records):
            sizes.append(len(records))
            return update(records)

        Scheduler = type(self.env["stock.scheduler"])
        total = self.Orderpoint.search_count([("product_id.active", "=", True)])
        with (
            patch.object(Scheduler, "_BATCH_SIZE", 2),
            patch.object(Orderpoint, "_update_stored_values", recording),
        ):
            self.env["stock.scheduler"]._update_orderpoint_values()
        self.assertEqual(sum(sizes), total)
        self.assertLessEqual(max(sizes), 2)

    def test_the_procurement_origin_lists_references_in_order(self):
        product = self._product("Origins")
        orderpoint = self._orderpoint(product, trigger="auto")
        first, second = self.env["stock.reference"].create(
            [{"name": "Audit REF A"}, {"name": "Audit REF B"}],
        )
        procurement = orderpoint.with_context(
            origins={orderpoint.id: [second.id, first.id]},
        )._prepare_procurements({})[0]
        self.assertTrue(procurement.origin.endswith("Audit REF A,Audit REF B"))
        self.assertEqual(procurement.values["reference_ids"], first | second)

    def test_a_route_of_one_company_rejects_a_rule_of_another(self):
        other_company = self.env["res.company"].create({"name": "Audit Other Co"})
        route = self.env["stock.route"].create(
            {"name": "Audit Shared", "company_id": False}
        )
        self.env["stock.rule"].create(
            {
                "name": "Audit rule",
                "route_id": route.id,
                "action": "pull",
                "location_src_id": self.stock_location.id,
                "location_dest_id": self.customers.id,
                "picking_type_id": self.warehouse.out_type_id.id,
                "company_id": self.env.company.id,
            },
        )
        with self.assertRaises(ValidationError):
            route.company_id = other_company

    def test_the_rule_report_draws_a_rule_to_its_own_destination(self):
        supplier = self.env["stock.warehouse"].create(
            {"name": "Audit RS", "code": "ARS"}
        )
        demand = self.env["stock.warehouse"].create(
            {
                "name": "Audit RD",
                "code": "ARD",
                "resupply_wh_ids": [Command.set(supplier.ids)],
            },
        )
        route = self.env["stock.route"].search(
            [("supplier_wh_id", "=", supplier.id), ("supplied_wh_id", "=", demand.id)],
        )
        leg = route.rule_ids.filtered("location_dest_from_rule")
        self.assertTrue(leg)
        product = self._product("Rule Report", route_ids=[Command.set(route.ids)])
        Report = self.env["report.stock.report_stock_rule"]
        self.assertEqual(
            Report._get_rule_loc(leg, product)["destination"],
            leg.location_dest_id,
        )
        elsewhere = self._orderpoint(
            product,
            warehouse_id=self.warehouse.id,
            location_id=self.stock_location.id,
        )
        values = Report._get_report_values(
            None,
            {"product_id": product.id, "warehouse_ids": (supplier | demand).ids},
        )
        self.assertNotIn(elsewhere.location_id, values["locations"])
