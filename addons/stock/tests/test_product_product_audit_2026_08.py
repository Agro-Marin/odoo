import datetime

from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tests import TransactionCase, tagged

from odoo.addons.stock.tools.quantity import QuantityFilters


@tagged("post_install", "-at_install")
class TestProductProductAudit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.Product = cls.env["product.product"]
        cls.product = cls.Product.create(
            {"name": "Audit 0822", "type": "consu", "is_storable": True},
        )

    def _move(self, qty, source, dest, state=None, product=None):
        move = self.env["stock.move"].create(
            {
                "product_id": (product or self.product).id,
                "product_uom_qty": qty,
                "location_id": source.id,
                "location_dest_id": dest.id,
            },
        )
        if state:
            move.state = state
        return move


    def test_a_bare_from_date_starts_the_readers_day_not_utcs(self):
        day = datetime.date(2020, 1, 15)
        for tz, expected in (
            ("UTC", datetime.datetime(2020, 1, 15, 0, 0, 0)),
            ("America/Mexico_City", datetime.datetime(2020, 1, 15, 6, 0, 0)),
            ("Pacific/Auckland", datetime.datetime(2020, 1, 14, 11, 0, 0)),
        ):
            scoped = self.Product.with_context(tz=tz)
            for value in (day, "2020-01-15"):
                with self.subTest(tz=tz, value=value):
                    self.assertEqual(
                        scoped._normalize_quantities_from_date(value),
                        expected,
                        "a bare from_date must start the reader's day",
                    )

    def test_the_two_ends_of_a_bare_window_agree_on_the_timezone(self):
        scoped = self.Product.with_context(tz="America/Mexico_City")
        start = scoped._normalize_quantities_from_date("2020-01-15")
        end, __ = scoped._normalize_quantities_to_date("2020-01-15")
        self.assertEqual(start, datetime.datetime(2020, 1, 15, 6, 0, 0))
        self.assertLess(end - start, datetime.timedelta(days=1))
        self.assertGreater(end - start, datetime.timedelta(hours=23, minutes=59))

    def test_a_from_date_carrying_a_time_is_left_alone(self):
        scoped = self.Product.with_context(tz="America/Mexico_City")
        precise = datetime.datetime(2020, 1, 15, 9, 30, 0)
        self.assertEqual(scoped._normalize_quantities_from_date(precise), precise)
        self.assertEqual(
            scoped._normalize_quantities_from_date("2020-01-15 09:30:00"),
            precise,
        )
        self.assertFalse(scoped._normalize_quantities_from_date(False))

    def test_the_scope_carries_the_normalized_from_date(self):
        scoped = self.Product.with_context(tz="America/Mexico_City")
        scope = scoped.browse()._prepare_quantities_scope(
            QuantityFilters(from_date="2020-01-15")
        )
        bounds = [
            condition.value
            for condition in scope.move_in_todo.iter_conditions()
            if condition.field_expr == "date"
        ]
        self.assertEqual(
            bounds,
            [datetime.datetime(2020, 1, 15, 6, 0, 0)],
            "the scope must carry the converted bound, not the raw string",
        )


    def test_owners_is_a_parameter_and_no_longer_a_hidden_context_read(self):
        Product = self.env["product.product"]
        base = (Domain.TRUE, Domain.TRUE, Domain.TRUE)

        untouched = Product._narrow_quantity_domains(*base, QuantityFilters())
        self.assertEqual([repr(d) for d in untouched], [repr(d) for d in base])

        quant, move_in, move_out = Product._narrow_quantity_domains(
            *base, QuantityFilters(owners=[7])
        )
        for rendered in (repr(quant), repr(move_in), repr(move_out)):
            self.assertIn("owner_id", rendered)
        self.assertIn("move_line_ids.owner_id", repr(move_in))

        no_owner = Product._narrow_quantity_domains(*base, QuantityFilters(owners=[]))[
            0
        ]
        self.assertIn("False", repr(no_owner), "empty owners means held by nobody")

        from_context = Product.with_context(owners=[7])._narrow_quantity_domains(
            *base, QuantityFilters.from_context(Product.with_context(owners=[7]).env)
        )
        self.assertEqual(
            [repr(d) for d in from_context],
            [repr(d) for d in (quant, move_in, move_out)],
            "the context route and the parameter route must build one domain",
        )

    def test_the_fast_path_guard_reads_the_same_object_the_filters_do(self):
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": self.product.id,
                "location_id": self.stock_location.id,
                "inventory_quantity": 4,
            },
        )._apply_inventory()
        self.env.invalidate_all()
        calls = []
        Product = type(self.env["product.product"])
        original = Product._search_qty_available_from_quants

        def counting(records, operator, value, filters=None):
            calls.append(filters)
            return original(records, operator, value, filters)

        Product._search_qty_available_from_quants = counting
        try:
            self.assertIn(
                self.product,
                self.env["product.product"].search([("qty_available", ">", 0)]),
            )
            self.assertEqual(len(calls), 1, "no owners scope: the fast path answers")
            self.env["product.product"].with_context(owners=[]).search(
                [("qty_available", ">", 0)]
            )
            self.assertEqual(
                len(calls), 1, "an owners scope must not reach the quant fast path"
            )
        finally:
            Product._search_qty_available_from_quants = original

    def test_a_filter_change_in_an_override_names_only_what_it_changes(self):
        filters = QuantityFilters(lot_id=False, owners=[3], from_date="2020-01-01")
        moved = filters._replace(to_date="2020-06-30")
        self.assertEqual(moved.to_date, "2020-06-30")
        self.assertEqual(
            (moved.lot_id, moved.owners, moved.from_date),
            (False, [3], "2020-01-01"),
            "everything the override did not name must survive",
        )

    def test_stock_subtracts_no_order_delay_of_its_own(self):
        from collections import defaultdict

        delays = defaultdict(float)
        self.assertEqual(self.product._get_order_lead_days(delays), 0.0)
        self.assertEqual(
            dict(delays), {}, "reading the delays must not invent an entry in them"
        )


    def test_the_route_priority_survives_every_hop_of_the_chain(self):
        Location = self.env["stock.location"]
        view = self.warehouse.view_location_id
        far = Location.create(
            {"name": "Audit 0822 far", "usage": "internal", "location_id": view.id},
        )
        near = Location.create(
            {"name": "Audit 0822 near", "usage": "internal", "location_id": view.id},
        )
        route = self.env["stock.route"].create(
            {
                "name": "Audit 0822 two hops",
                "product_selectable": True,
                "rule_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Audit 0822 near -> stock",
                            "action": "pull",
                            "picking_type_id": self.warehouse.int_type_id.id,
                            "location_src_id": near.id,
                            "location_dest_id": self.stock_location.id,
                            "procure_method": "make_to_order",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Audit 0822 far -> near",
                            "action": "pull",
                            "picking_type_id": self.warehouse.int_type_id.id,
                            "location_src_id": far.id,
                            "location_dest_id": near.id,
                            "procure_method": "make_to_stock",
                        },
                    ),
                ],
            },
        )
        self.product.route_ids = [(6, 0, route.ids)]

        seen = []
        Rule = type(self.env["stock.rule"])
        original = Rule._get_rule

        def spy(records, product_id, location_id, values):
            seen.append(values.get("route_ids"))
            return original(records, product_id, location_id, values)

        Rule._get_rule = spy
        try:
            rules = self.product._get_rules_from_location(
                self.stock_location, route_ids=route
            )
        finally:
            Rule._get_rule = original

        self.assertEqual(
            len(rules), 2, "fixture: both hops of the chain must be walked"
        )
        self.assertGreater(len(seen), 1, "fixture: the chain must actually recurse")
        for hop, passed in enumerate(seen):
            with self.subTest(hop=hop):
                self.assertEqual(
                    passed,
                    route,
                    "every hop must carry the route the caller asked for",
                )

    def test_a_deleted_location_in_the_context_does_not_break_view_loading(self):
        doomed = self.env["stock.location"].create(
            {
                "name": "Audit 0822 doomed",
                "usage": "internal",
                "location_id": self.warehouse.view_location_id.id,
            },
        )
        location_id = doomed.id
        doomed.unlink()
        scoped = self.Product.with_context(
            active_id=location_id, active_model="stock.location"
        )
        self.assertFalse(scoped.view_header_get(False, "list"))

    def test_a_live_location_in_the_context_still_names_the_header(self):
        scoped = self.Product.with_context(
            active_id=self.stock_location.id, active_model="stock.location"
        )
        self.assertIn(self.stock_location.name, scoped.view_header_get(False, "list"))


    def test_the_scoped_labels_still_resolve_in_the_readers_language(self):
        import odoo.tools.translate as translate_module

        asked = []
        original = translate_module.get_translation

        def recording(module, lang, source, args=None):
            asked.append((lang, source))
            return original(module, lang, source, args)

        translate_module.get_translation = recording
        try:
            scoped = self.Product.with_context(
                location=self.customer_location.id, lang="en_US"
            )
            res = scoped.fields_get(["qty_available", "qty_available_virtual"])
        finally:
            translate_module.get_translation = original

        self.assertEqual(res["qty_available"]["string"], "Delivered Qty")
        self.assertEqual(res["qty_available_virtual"]["string"], "Future Deliveries")
        sources = [source for __, source in asked]
        self.assertIn("Delivered Qty", sources)
        self.assertIn("Future Deliveries", sources)
        self.assertNotIn(
            "Future Receipts",
            sources,
            "only the labels this scope uses may be translated",
        )
        self.assertEqual(
            {lang for lang, __ in asked},
            {"en_US"},
            "the reader's language, not whatever the module-level table was built under",
        )


    def test_setting_a_quantity_on_a_service_variant_is_refused_not_ignored(self):
        service = self.Product.create({"name": "Audit 0822 svc", "type": "service"})
        with self.assertRaises(UserError) as caught:
            service.qty_available = 5
        self.assertIn("does not track inventory", str(caught.exception))

    def test_setting_a_quantity_on_a_non_storable_variant_is_refused(self):
        consu = self.Product.create(
            {"name": "Audit 0822 consu", "type": "consu", "is_storable": False},
        )
        with self.assertRaises(UserError) as caught:
            consu.qty_available = 3
        self.assertIn("does not track inventory", str(caught.exception))

    def test_a_zero_quantity_on_an_ineligible_variant_stays_a_no_op(self):
        service = self.Product.create({"name": "Audit 0822 svc0", "type": "service"})
        service.qty_available = 0
        self.assertFalse(service.stock_quant_ids)

    def test_setting_a_quantity_on_a_tracked_variant_is_refused(self):
        tracked = self.Product.create(
            {
                "name": "Audit 0822 lot",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
            },
        )
        with self.assertRaises(UserError) as caught:
            tracked.qty_available = 7
        self.assertIn("lot/serial number", str(caught.exception))
        self.assertFalse(
            tracked.stock_quant_ids.filtered(lambda q: not q.lot_id and q.quantity)
        )

    def test_the_reason_is_reported_before_the_sign(self):
        service = self.Product.create({"name": "Audit 0822 neg", "type": "service"})
        with self.assertRaises(UserError) as caught:
            service.qty_available = -5
        self.assertIn("does not track inventory", str(caught.exception))

    def test_the_template_path_still_reports_the_templates_own_wording(self):
        tmpl = self.env["product.template"].create(
            {
                "name": "Audit 0822 tmpl",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
            },
        )
        with self.assertRaises(UserError) as caught:
            tmpl.write({"qty_available": 4})
        self.assertIn("lot/serial number", str(caught.exception))


    def test_a_company_without_a_warehouse_does_not_drop_the_other_companys_write(
        self,
    ):
        Warehouse = self.env["stock.warehouse"]
        second = self.env["res.company"].create({"name": "Audit 0822 No WH"})
        Warehouse.search([("company_id", "=", second.id)]).action_archive()
        self.assertFalse(
            Warehouse.search([("company_id", "=", second.id)]),
            "fixture: no warehouse may be visible for the second company",
        )
        original = type(Warehouse)._warehouse_redirect_warning
        type(Warehouse)._warehouse_redirect_warning = lambda records: None
        try:
            for index, reversed_order in enumerate((False, True)):
                stranded = self.Product.create(
                    {
                        "name": f"Audit 0822 stranded {index}",
                        "type": "consu",
                        "is_storable": True,
                        "company_id": second.id,
                    },
                )
                served = self.Product.create(
                    {
                        "name": f"Audit 0822 served {index}",
                        "type": "consu",
                        "is_storable": True,
                        "company_id": self.env.company.id,
                    },
                )
                products = stranded + served
                if reversed_order:
                    products = served + stranded
                with self.subTest(warehouseless_first=not reversed_order):
                    products._apply_qty_available([4.0] * len(products))
                    self.env.invalidate_all()
                    self.assertEqual(
                        served.qty_available,
                        4.0,
                        "the company that has a warehouse must still be served",
                    )
                    self.assertEqual(
                        stranded.qty_available,
                        0.0,
                        "the company that has none has nowhere to put it",
                    )
        finally:
            type(Warehouse)._warehouse_redirect_warning = original


    def test_a_single_non_internal_scope_is_told_what_is_actually_wrong(self):
        with self.assertRaises(UserError) as caught:
            self.Product.with_context(
                location=self.customer_location.id
            )._resolve_inventory_location()
        message = str(caught.exception)
        self.assertIn("not an internal location", message)
        self.assertNotIn("total over all of them", message)

    def test_two_locations_still_get_the_ambiguity_message(self):
        other = self.env["stock.location"].create(
            {
                "name": "Audit 0822 second",
                "usage": "internal",
                "location_id": self.warehouse.view_location_id.id,
            },
        )
        with self.assertRaises(UserError) as caught:
            self.Product.with_context(
                location=[self.stock_location.id, other.id]
            )._resolve_inventory_location()
        self.assertIn("total over all of them", str(caught.exception))


    def _two_company_reader_fixture(self):
        second = self.env["res.company"].create({"name": "Audit 0822 Reader Co"})
        warehouse = self.env["stock.warehouse"].create(
            {"name": "Audit 0822 WH", "code": "A82W", "company_id": second.id},
        )
        groups = [
            (4, self.env.ref("stock.group_stock_manager").id),
            (4, self.env.ref("base.group_user").id),
        ]
        users = self.env["res.users"].create(
            [
                {
                    "name": "audit0822-a",
                    "login": "audit0822-a",
                    "company_id": self.env.company.id,
                    "company_ids": [(6, 0, [self.env.company.id])],
                    "group_ids": groups,
                },
                {
                    "name": "audit0822-b",
                    "login": "audit0822-b",
                    "company_id": second.id,
                    "company_ids": [(6, 0, [second.id])],
                    "group_ids": groups,
                },
            ],
        )
        product = self.Product.create(
            {
                "name": "Audit 0822 reader",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
            },
        )
        Lot = self.env["stock.lot"]
        lots = {}
        for name, company, location in (
            ("A82-a", self.env.company, self.stock_location),
            ("A82-b", self.env.company, self.stock_location),
            ("A82-c", second, warehouse.lot_stock_id),
        ):
            lots[name] = Lot.create(
                {
                    "name": name,
                    "product_id": product.id,
                    "company_id": company.id,
                    "location_id": location.id,
                },
            )
        Quant = self.env["stock.quant"].sudo()
        Quant.create(
            {
                "product_id": product.id,
                "location_id": self.stock_location.id,
                "quantity": 5,
                "lot_id": lots["A82-a"].id,
            },
        )
        Quant.create(
            {
                "product_id": product.id,
                "location_id": warehouse.lot_stock_id.id,
                "quantity": 9,
                "lot_id": lots["A82-c"].id,
            },
        )
        self.env.flush_all()
        return product, users[0], users[1], second

    def test_a_second_reader_does_not_inherit_the_firsts_quantities(self):
        product, first, second, __ = self._two_company_reader_fixture()
        truth = {first: 5.0, second: 9.0}
        for order in ((first, second), (second, first)):
            self.env.invalidate_all()
            for user in order:
                with self.subTest(first_reader=order[0].login, reader=user.login):
                    self.assertEqual(product.with_user(user).qty_available, truth[user])

    def test_a_second_reader_does_not_inherit_the_firsts_lot_count(self):
        product, first, second, __ = self._two_company_reader_fixture()
        truth = {first: 2, second: 1}
        for order in ((first, second), (second, first)):
            self.env.invalidate_all()
            for user in order:
                with self.subTest(first_reader=order[0].login, reader=user.login):
                    self.assertEqual(product.with_user(user).count_lot_ids, truth[user])
                    self.assertEqual(
                        product.product_tmpl_id.with_user(user).count_lot_ids,
                        truth[user],
                    )

    def test_the_lot_count_is_not_reused_across_company_scopes(self):
        second = self.env["res.company"].create({"name": "Audit 0822 Co"})
        self.env.user.company_ids = [(4, second.id)]
        second_location = self.env["stock.location"].create(
            {
                "name": "Audit 0822 Co Stock",
                "usage": "internal",
                "company_id": second.id,
            },
        )
        tracked = self.Product.create(
            {
                "name": "Audit 0822 badge",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
            },
        )
        Lot = self.env["stock.lot"]
        Lot.create(
            {
                "name": "A0822-1",
                "product_id": tracked.id,
                "company_id": self.env.company.id,
                "location_id": self.stock_location.id,
            },
        )
        Lot.create(
            {
                "name": "A0822-2",
                "product_id": tracked.id,
                "company_id": second.id,
                "location_id": second_location.id,
            },
        )
        both = [self.env.company.id, second.id]
        for order in (
            (both, [self.env.company.id]),
            ([self.env.company.id], both),
        ):
            self.env.invalidate_all()
            for companies in order:
                with self.subTest(companies=companies):
                    self.assertEqual(
                        tracked.with_context(
                            allowed_company_ids=companies
                        ).count_lot_ids,
                        len(companies),
                    )
                    self.assertEqual(
                        tracked.product_tmpl_id.with_context(
                            allowed_company_ids=companies
                        ).count_lot_ids,
                        len(companies),
                    )


    def test_a_draft_or_cancelled_move_does_not_make_a_search_candidate(self):
        drafted = self.Product.create(
            {"name": "Audit 0822 draft", "type": "consu", "is_storable": True},
        )
        cancelled = self.Product.create(
            {"name": "Audit 0822 cancel", "type": "consu", "is_storable": True},
        )
        self._move(3, self.supplier_location, self.stock_location, product=drafted)
        move = self._move(
            3, self.supplier_location, self.stock_location, product=cancelled
        )
        move._action_confirm()
        move._action_cancel()

        candidates = self.Product._get_quantity_search_candidates()
        self.assertNotIn(drafted, candidates)
        self.assertNotIn(cancelled, candidates)

    def test_dropping_them_does_not_change_who_answers_a_search(self):
        drafted = self.Product.create(
            {"name": "Audit 0822 draft2", "type": "consu", "is_storable": True},
        )
        self._move(3, self.supplier_location, self.stock_location, product=drafted)
        self.env.invalidate_all()
        self.assertEqual(drafted.qty_incoming, 0.0)
        self.assertIn(drafted, self.Product.search([("qty_incoming", "=", 0)]))
        self.assertNotIn(drafted, self.Product.search([("qty_incoming", ">", 0)]))

    def test_a_confirmed_move_is_still_a_candidate(self):
        incoming = self.Product.create(
            {"name": "Audit 0822 confirmed", "type": "consu", "is_storable": True},
        )
        move = self._move(
            4, self.supplier_location, self.stock_location, product=incoming
        )
        move._action_confirm()
        self.assertIn(incoming, self.Product._get_quantity_search_candidates())
        self.assertIn(incoming, self.Product.search([("qty_incoming", ">", 0)]))


    def test_variant_and_template_searches_agree_on_the_same_stock(self):
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": self.product.id,
                "location_id": self.stock_location.id,
                "inventory_quantity": 9,
            },
        )._apply_inventory()
        self.env.invalidate_all()
        Template = self.env["product.template"]
        self.assertIn(self.product, self.Product.search([("qty_available", "=", 9)]))
        self.assertIn(
            self.product.product_tmpl_id,
            Template.search([("qty_available", "=", 9)]),
        )
        self.assertNotIn(
            self.product.product_tmpl_id,
            Template.search([("qty_available", ">", 9)]),
        )
        self.assertIn(
            self.product.product_tmpl_id,
            Template.search([("qty_available", "<", 10)]),
        )

    def test_a_template_with_nothing_in_scope_still_answers_zero(self):
        empty = self.env["product.template"].create(
            {"name": "Audit 0822 empty", "type": "consu", "is_storable": True},
        )
        self.assertIn(
            empty, self.env["product.template"].search([("qty_available", "=", 0)])
        )
        self.assertNotIn(
            empty, self.env["product.template"].search([("qty_available", ">", 0)])
        )
