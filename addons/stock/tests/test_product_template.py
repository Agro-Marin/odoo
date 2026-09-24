from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductTemplateStockInvariants(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tmpl = cls.env["product.template"]

    def _assert_refused(self, callback):
        with self.assertRaises(ValidationError) as caught:
            callback()
        self.assertRegex(
            str(caught.exception),
            "cannot track inventory|cannot be\n? *tracked by lot",
        )

    def test_a_service_cannot_be_created_tracking_inventory(self):
        self._assert_refused(
            lambda: self.Tmpl.create(
                {"name": "svc", "type": "service", "is_storable": True},
            ),
        )

    def test_a_combo_cannot_be_created_tracking_inventory(self):
        choice = self.env["product.combo"].create(
            {
                "name": "audit choice",
                "combo_item_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.Tmpl.create(
                                {"name": "combo member", "type": "consu"},
                            ).product_variant_id.id,
                        },
                    ),
                ],
            },
        )
        self._assert_refused(
            lambda: self.Tmpl.create(
                {
                    "name": "combo",
                    "type": "combo",
                    "is_storable": True,
                    "combo_ids": [(6, 0, choice.ids)],
                },
            ),
        )

    def test_the_variant_model_is_guarded_too(self):
        self._assert_refused(
            lambda: self.env["product.product"].create(
                {"name": "svc variant", "type": "service", "is_storable": True},
            ),
        )
        service = self.Tmpl.create({"name": "svc3", "type": "service"})
        self._assert_refused(
            lambda: service.product_variant_id.write({"is_storable": True}),
        )

    def test_writing_both_at_once_no_longer_bypasses_the_compute(self):
        template = self.Tmpl.create(
            {"name": "goods", "type": "consu", "is_storable": True},
        )
        self._assert_refused(
            lambda: template.write({"type": "service", "is_storable": True}),
        )

    def test_the_action_context_default_does_not_break_the_form(self):
        form = Form(self.Tmpl.with_context(default_is_storable=True))
        form.name = "from a default_is_storable action"
        self.assertTrue(form.is_storable)
        form.type = "service"
        self.assertFalse(form.is_storable)
        record = form.save()
        self.assertEqual((record.type, record.is_storable), ("service", False))

    def test_changing_the_type_alone_still_normalises_silently(self):
        template = self.Tmpl.create(
            {"name": "goods2", "type": "consu", "is_storable": True, "tracking": "lot"},
        )
        template.write({"type": "service"})
        self.assertFalse(template.is_storable)
        self.assertEqual(template.tracking, "none")

    def test_the_client_save_path_still_works(self):
        template = self.Tmpl.create(
            {"name": "web", "type": "consu", "is_storable": True, "tracking": "lot"},
        )
        onchange = template.onchange(
            {
                "id": template.id,
                "type": "service",
                "is_storable": True,
                "tracking": "lot",
            },
            ["type"],
            {"type": {}, "is_storable": {}, "tracking": {}},
        )
        self.assertEqual(
            onchange["value"],
            {"is_storable": False, "tracking": "none"},
        )
        template.web_save({"type": "service"}, {"is_storable": {}, "tracking": {}})
        self.assertEqual((template.type, template.is_storable), ("service", False))

    def test_a_non_storable_product_cannot_be_lot_tracked(self):
        self._assert_refused(
            lambda: self.Tmpl.create(
                {
                    "name": "untracked",
                    "type": "consu",
                    "is_storable": False,
                    "tracking": "lot",
                },
            ),
        )

    def test_tracking_defaulted_onto_a_non_storable_product_is_refused(self):
        self._assert_refused(
            lambda: self.Tmpl.create({"name": "implicit", "tracking": "lot"}),
        )

    def test_assignment_order_matters_and_is_documented(self):
        template = self.Tmpl.create({"name": "order", "type": "consu"})
        self._assert_refused(lambda: setattr(template, "tracking", "serial"))

        template.is_storable = True
        template.tracking = "serial"
        self.assertEqual(template.tracking, "serial")

        other = self.Tmpl.create({"name": "order2", "type": "consu"})
        other.write({"is_storable": True, "tracking": "serial"})
        self.assertEqual(other.tracking, "serial")

    def test_a_variant_write_naming_both_is_order_independent(self):
        for index, vals in enumerate(
            (
                {"is_storable": True, "tracking": "serial"},
                {"tracking": "serial", "is_storable": True},
            ),
        ):
            variant = self.env["product.product"].create(
                {"name": f"split {index}", "type": "consu"},
            )
            variant.write(vals)
            self.assertEqual(
                (variant.is_storable, variant.tracking),
                (True, "serial"),
                f"a variant write is not atomic for {list(vals)}",
            )

    def test_a_variant_write_still_refuses_a_real_contradiction(self):
        variant = self.env["product.product"].create(
            {"name": "split bad", "type": "consu"},
        )
        self._assert_refused(
            lambda: variant.write({"type": "service", "is_storable": True}),
        )

    def test_clearing_storability_still_clears_tracking_silently(self):
        template = self.Tmpl.create(
            {"name": "drop", "type": "consu", "is_storable": True, "tracking": "lot"},
        )
        template.write({"is_storable": False})
        self.assertEqual(template.tracking, "none")

    def test_a_storable_product_is_still_free_to_be_lot_tracked(self):
        template = self.Tmpl.create(
            {"name": "ok", "type": "consu", "is_storable": True, "tracking": "lot"},
        )
        self.assertEqual(template.tracking, "lot")


@tagged("post_install", "-at_install")
class TestSerialPrefixSequences(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tmpl = cls.env["product.template"]

    def test_returning_to_a_prefix_resumes_its_numbering(self):
        template = self.Tmpl.create(
            {
                "name": "prefix reuse",
                "type": "consu",
                "is_storable": True,
                "tracking": "serial",
            },
        )
        template.serial_prefix_format = "ZZZ-"
        self.env.flush_all()
        first = template.lot_sequence_id
        drawn = [first.next_by_id() for _ in range(3)]
        self.assertEqual(drawn, ["ZZZ-0000001", "ZZZ-0000002", "ZZZ-0000003"])

        template.serial_prefix_format = "YYY-"
        self.env.flush_all()
        self.assertNotEqual(template.lot_sequence_id, first)
        self.assertTrue(
            first.exists(),
            "the sequence for ZZZ- still owns the numbering for ZZZ-",
        )

        template.serial_prefix_format = "ZZZ-"
        self.env.flush_all()
        self.assertEqual(template.lot_sequence_id, first)
        self.assertEqual(
            template.lot_sequence_id.preview_next(),
            "ZZZ-0000004",
            "returning to a prefix must not reissue names already drawn",
        )

    def test_clearing_the_prefix_returns_to_the_standard_sequence(self):
        template = self.Tmpl.create(
            {
                "name": "prefix clear",
                "type": "consu",
                "is_storable": True,
                "tracking": "serial",
            },
        )
        template.serial_prefix_format = "QQQ-"
        self.env.flush_all()
        template.serial_prefix_format = ""
        self.env.flush_all()
        self.assertEqual(
            template.lot_sequence_id,
            self.Tmpl._default_lot_sequence_id(),
        )


@tagged("post_install", "-at_install")
class TestProductTemplateStorabilityOff(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tmpl = cls.env["product.template"]
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customers = cls.env.ref("stock.stock_location_customers")

    def _stocked_product(self, name, quantity=10.0):
        template = self.Tmpl.create(
            {"name": name, "type": "consu", "is_storable": True},
        )
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": template.product_variant_id.id,
                "location_id": self.stock_location.id,
                "inventory_quantity": quantity,
            },
        )._apply_inventory()
        return template

    def _reserved_delivery(self, product, quantity=4.0):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": quantity,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customers.id,
                "company_id": self.env.company.id,
            },
        )
        move._action_confirm()
        move._action_assign()
        return move

    def _get_quant(self, product):
        return self.env["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
            ],
        )

    def test_turning_storability_off_releases_the_reservation(self):
        template = self._stocked_product("strand")
        product = template.product_variant_id
        move = self._reserved_delivery(product)
        self.assertEqual(self._get_quant(product).reserved_quantity, 4.0)

        template.write({"is_storable": False})

        self.assertEqual(
            self._get_quant(product).reserved_quantity,
            0.0,
            "turning inventory tracking off must release what nothing else can",
        )
        move._action_cancel()

    def test_validating_the_move_afterwards_leaves_nothing_reserved(self):
        template = self._stocked_product("strand2")
        product = template.product_variant_id
        move = self._reserved_delivery(product)
        template.write({"is_storable": False})

        move.quantity = 4.0
        move.picked = True
        move._action_done()

        quant = self._get_quant(product)
        self.assertEqual(quant.reserved_quantity, 0.0)
        self.assertEqual(
            product.qty_free,
            quant.quantity,
            "qty_free must not stay short by a reservation nobody owns",
        )

    def test_what_the_release_leaves_behind_is_the_move(self):
        template = self._stocked_product("leftover")
        product = template.product_variant_id
        move = self._reserved_delivery(product)

        template.write({"is_storable": False})
        self.env.invalidate_all()

        self.assertEqual(self._get_quant(product).reserved_quantity, 0.0)
        self.assertEqual(product.qty_free, 10.0)
        self.assertEqual(move.state, "assigned")
        self.assertEqual(sum(move.move_line_ids.mapped("quantity")), 4.0)

        move._unreserve()
        self.assertEqual(move.state, "confirmed")
        self.assertFalse(move.move_line_ids)
        self.assertEqual(self._get_quant(product).reserved_quantity, 0.0)

    def test_turning_storability_on_still_resets_the_inventory(self):
        template = self.Tmpl.create(
            {"name": "flipon", "type": "consu", "is_storable": False},
        )
        product = template.product_variant_id
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 5.0,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.stock_location.id,
                "company_id": self.env.company.id,
            },
        )
        move._action_confirm()
        move.quantity = 5.0
        move.picked = True
        move._action_done()

        template.write({"is_storable": True})

        self.assertEqual(product.qty_available, 0.0)
        self.assertTrue(
            self.env["stock.move"].search_count(
                [
                    ("product_id", "=", product.id),
                    ("location_dest_id.usage", "=", "inventory"),
                    ("state", "=", "done"),
                ],
            ),
            "the ledger/stock disagreement must be booked, not left implicit",
        )

    def test_toggling_storability_off_and_on_books_nothing(self):
        template = self._stocked_product("roundtrip")
        product = template.product_variant_id
        moves_before = self.env["stock.move"].search_count(
            [("product_id", "=", product.id)],
        )

        template.write({"is_storable": False})
        template.write({"is_storable": True})

        self.assertEqual(product.qty_available, 10.0)
        self.assertEqual(
            self.env["stock.move"].search_count([("product_id", "=", product.id)]),
            moves_before,
            "a history that already matches the quants needs no adjustment",
        )
        self.assertEqual(
            sum(
                self.env["stock.quant"]
                .search(
                    [
                        ("product_id", "=", product.id),
                        ("location_id.usage", "=", "internal"),
                    ]
                )
                .mapped("quantity"),
            ),
            10.0,
        )

    def test_moves_done_while_not_storable_are_balanced_against_on_hand(self):
        template = self._stocked_product("drift")
        product = template.product_variant_id
        template.write({"is_storable": False})
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 3.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id,
                "company_id": self.env.company.id,
            },
        )
        move._action_confirm()
        move.quantity = 3.0
        move.picked = True
        move._action_done()

        template.write({"is_storable": True})

        self.assertEqual(product.qty_available, 10.0)
        history = sum(
            line.quantity_product_uom
            * (1 if line.location_dest_id == self.stock_location else -1)
            for line in self.env["stock.move.line"].search(
                [("product_id", "=", product.id), ("state", "=", "done")],
            )
        )
        self.assertEqual(
            history, 10.0, "the move history must end where the quants are"
        )


@tagged("post_install", "-at_install")
class TestProductTemplateQuantityMessages(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tmpl = cls.env["product.template"]

    def test_an_archived_only_template_is_not_told_to_save_itself(self):
        template = self.Tmpl.create(
            {"name": "archived", "type": "consu", "is_storable": True},
        )
        template.product_variant_ids.write({"active": False})
        self.assertFalse(template.product_variant_id)

        with self.assertRaises(UserError) as caught:
            template.qty_available = 3.0

        message = str(caught.exception)
        self.assertIn("no active variant", message)
        self.assertNotIn(
            "Save the product form",
            message,
            "the template is saved; saving it again changes nothing",
        )

    def test_an_unsaved_template_is_still_told_to_save(self):
        template = self.Tmpl.new(
            {
                "name": "unsaved",
                "type": "consu",
                "is_storable": True,
                "tracking": "none",
            },
        )
        self.assertFalse(template.id)
        self.assertFalse(template.product_variant_id)
        with self.assertRaises(UserError) as caught:
            template._check_qty_available_update([3.0])
        self.assertIn("Save the product form", str(caught.exception))


@tagged("post_install", "-at_install")
class TestProductTemplateReaderScopedComputes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tmpl = cls.env["product.template"]
        multi_locations = cls.env.ref("stock.group_stock_multi_locations")
        stock_user = cls.env.ref("stock.group_stock_user")
        internal = cls.env.ref("base.group_user")
        cls.env.ref("base.group_user").implied_ids -= (
            multi_locations
            | cls.env.ref("stock.group_tracking_owner")
            | cls.env.ref("stock.group_tracking_lot")
        )
        cls.privileged = cls.env["res.users"].create(
            {
                "name": "advanced stock reader",
                "login": "pt_audit_advanced",
                "group_ids": [
                    (6, 0, [internal.id, stock_user.id, multi_locations.id]),
                ],
            },
        )
        cls.plain = cls.env["res.users"].create(
            {
                "name": "plain stock reader",
                "login": "pt_audit_plain",
                "group_ids": [(6, 0, [internal.id, stock_user.id])],
            },
        )

    def _assert_discriminating(self):
        self.assertTrue(
            self.Tmpl.with_user(self.privileged)._has_advanced_stock_option()
        )
        self.assertFalse(
            self.Tmpl.with_user(self.plain)._has_advanced_stock_option(),
            "something granted the advanced groups to every internal user",
        )

    def _both_orders_of(self, first, second, field_name):
        self.env.invalidate_all()
        forward = (first[field_name], second[field_name])
        self.env.invalidate_all()
        backward = (second[field_name], first[field_name])
        return forward, (backward[1], backward[0])

    def test_show_qty_update_button_is_per_reader(self):
        self._assert_discriminating()
        template = self.Tmpl.create(
            {"name": "perreader", "type": "consu", "is_storable": True},
        )
        self.env.flush_all()
        forward, backward = self._both_orders_of(
            template.with_user(self.privileged),
            template.with_user(self.plain),
            "show_qty_update_button",
        )
        self.assertEqual(forward, backward, "read order decided the answer")
        self.assertEqual(forward, (True, False))

    def test_the_variant_field_is_per_reader_too(self):
        self._assert_discriminating()
        template = self.Tmpl.create(
            {"name": "perreader2", "type": "consu", "is_storable": True},
        )
        product = template.product_variant_id
        self.env.flush_all()
        forward, backward = self._both_orders_of(
            product.with_user(self.privileged),
            product.with_user(self.plain),
            "show_qty_update_button",
        )
        self.assertEqual(forward, backward, "read order decided the answer")
        self.assertEqual(forward, (True, False))

    def _route_scoped_setup(self):
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "Route audit B"})
        self.env["stock.route"].search([]).write({"product_selectable": False})
        self.env["stock.route"].create(
            {
                "name": "A only",
                "product_selectable": True,
                "company_id": company_a.id,
            },
        )
        template = self.Tmpl.create(
            {"name": "routescope", "type": "consu", "is_storable": True},
        )
        self.env.flush_all()
        return company_a, company_b, template

    def _both_orders(self, first, second):
        self.env.invalidate_all()
        forward = (
            first.has_available_route_ids,
            second.has_available_route_ids,
        )
        self.env.invalidate_all()
        backward = (
            second.has_available_route_ids,
            first.has_available_route_ids,
        )
        return forward, (backward[1], backward[0])

    def test_route_availability_is_not_shared_between_users(self):
        company_a, company_b, template = self._route_scoped_setup()
        internal = self.env.ref("base.group_user")
        stock_user = self.env.ref("stock.group_stock_user")
        in_a = self.env["res.users"].create(
            {
                "name": "route reader A",
                "login": "pt_audit_route_a",
                "company_id": company_a.id,
                "company_ids": [(6, 0, [company_a.id])],
                "group_ids": [(6, 0, [internal.id, stock_user.id])],
            },
        )
        in_b = self.env["res.users"].create(
            {
                "name": "route reader B",
                "login": "pt_audit_route_b",
                "company_id": company_b.id,
                "company_ids": [(6, 0, [company_b.id])],
                "group_ids": [(6, 0, [internal.id, stock_user.id])],
            },
        )
        forward, backward = self._both_orders(
            template.with_user(in_a),
            template.with_user(in_b),
        )
        self.assertEqual(forward, backward, "read order decided the answer")
        self.assertEqual(
            forward,
            (True, False),
            "the company-A route must be visible to A and invisible to B",
        )

    def test_route_availability_follows_a_company_switch(self):
        company_a, company_b, template = self._route_scoped_setup()
        internal = self.env.ref("base.group_user")
        stock_user = self.env.ref("stock.group_stock_user")
        reader = self.env["res.users"].create(
            {
                "name": "route reader both",
                "login": "pt_audit_route_both",
                "company_id": company_a.id,
                "company_ids": [(6, 0, [company_a.id, company_b.id])],
                "group_ids": [(6, 0, [internal.id, stock_user.id])],
            },
        )
        scoped = template.with_user(reader)
        forward, backward = self._both_orders(
            scoped.with_context(allowed_company_ids=[company_a.id]),
            scoped.with_context(allowed_company_ids=[company_b.id]),
        )
        self.assertEqual(forward, backward, "read order decided the answer")
        self.assertEqual(
            forward,
            (True, False),
            "switching to company B must hide company A's route",
        )


@tagged("post_install", "-at_install")
class TestTemplateQuantityBatching(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tmpl = cls.env["product.template"]
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)],
            limit=1,
        )

    def _templates(self, count, tag):
        templates = self.Tmpl.create(
            [
                {"name": f"{tag}{index}", "type": "consu", "is_storable": True}
                for index in range(count)
            ],
        )
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            [
                {
                    "product_id": template.product_variant_id.id,
                    "location_id": self.warehouse.lot_stock_id.id,
                    "inventory_quantity": 7.0,
                }
                for template in templates
            ],
        )._apply_inventory()
        self.env.flush_all()
        return templates.ids

    def _cost(self, template_ids, field_name):
        self.env.invalidate_all()
        before = self.env.cr.sql_statement_count
        self.Tmpl.browse(template_ids).mapped(field_name)
        return self.env.cr.sql_statement_count - before

    def _assert_flat(self, field_name):
        small = self._templates(2, f"S{field_name}")
        large = self._templates(20, f"L{field_name}")
        self._cost(small, field_name)
        cost_small = self._cost(small, field_name)
        self._cost(large, field_name)
        cost_large = self._cost(large, field_name)
        self.assertEqual(
            cost_large,
            cost_small,
            f"{field_name} costs {cost_large} queries for 20 templates against "
            f"{cost_small} for 2 -- the variant prefetch set stopped batching it",
        )

    def test_qty_available_is_flat_in_the_number_of_templates(self):
        self._assert_flat("qty_available")

    def test_count_moves_in_is_flat_in_the_number_of_templates(self):
        self._assert_flat("count_moves_in")

    def test_count_lot_ids_is_flat_in_the_number_of_templates(self):
        self._assert_flat("count_lot_ids")


@tagged("post_install", "-at_install")
class TestProductTemplateEdgeCases(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tmpl = cls.env["product.template"]
        cls.wh = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.loc = cls.wh.lot_stock_id

    def _multi(self, name, nvals=2):
        attr = self.env["product.attribute"].create(
            {
                "name": f"{name}-a",
                "value_ids": [(0, 0, {"name": f"v{i}"}) for i in range(nvals)],
            }
        )
        return self.Tmpl.create(
            {
                "name": name,
                "type": "consu",
                "is_storable": True,
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": attr.id,
                            "value_ids": [(6, 0, attr.value_ids.ids)],
                        },
                    )
                ],
            }
        )

    def test_nonstorable_create_with_qty_raises(self):
        with self.assertRaises(UserError):
            self.Tmpl.create(
                {
                    "name": "V1",
                    "type": "consu",
                    "is_storable": False,
                    "qty_available": 9,
                }
            )

    def test_service_create_with_qty_raises(self):
        with self.assertRaises(UserError):
            self.Tmpl.create({"name": "V2", "type": "service", "qty_available": 9})

    def test_nonstorable_zero_qty_is_still_a_noop(self):
        res = self.Tmpl.web_save(
            {"name": "V3", "type": "service", "qty_available": 0.0},
            {"qty_available": {}},
        )
        self.assertEqual(res[0]["qty_available"], 0.0)

    def test_storable_create_still_applies(self):
        tmpl = self.Tmpl.create(
            {"name": "V4", "type": "consu", "is_storable": True, "qty_available": 7}
        )
        self.env.invalidate_all()
        self.assertEqual(tmpl.qty_available, 7.0)

    def test_multivariant_create_raises_like_write(self):
        attr = self.env["product.attribute"].create(
            {"name": "V5a", "value_ids": [(0, 0, {"name": "a"}), (0, 0, {"name": "b"})]}
        )
        with self.assertRaises(UserError):
            self.Tmpl.create(
                {
                    "name": "V5",
                    "type": "consu",
                    "is_storable": True,
                    "qty_available": 4,
                    "attribute_line_ids": [
                        (
                            0,
                            0,
                            {
                                "attribute_id": attr.id,
                                "value_ids": [(6, 0, attr.value_ids.ids)],
                            },
                        )
                    ],
                }
            )

    def test_tracked_write_raises_like_create(self):
        tmpl = self.Tmpl.create(
            {"name": "V6", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        with self.assertRaises(UserError):
            tmpl.qty_available = 5

    def test_create_does_not_mutate_caller_vals(self):
        vals = {"name": "V7", "type": "consu", "is_storable": True, "qty_available": 3}
        self.Tmpl.create([vals])
        self.assertIn("qty_available", vals)
        self.assertEqual(vals["qty_available"], 3)

    def test_search_matches_the_template_total(self):
        tmpl = self._multi("V8")
        v1, v2 = tmpl.product_variant_ids[0], tmpl.product_variant_ids[1]
        Q = self.env["stock.quant"]
        Q.create({"product_id": v1.id, "location_id": self.loc.id, "quantity": 5.0})
        Q.create({"product_id": v2.id, "location_id": self.loc.id, "quantity": -5.0})
        self.env.invalidate_all()
        self.assertEqual(tmpl.qty_available, 0.0)
        self.assertFalse(
            self.Tmpl.search([("id", "=", tmpl.id), ("qty_available", ">", 0)])
        )
        self.assertFalse(
            self.Tmpl.search([("id", "=", tmpl.id), ("qty_available", "<", 0)])
        )
        self.assertTrue(
            self.Tmpl.search([("id", "=", tmpl.id), ("qty_available", "=", 0)])
        )

    def test_search_sums_across_variants(self):
        tmpl = self._multi("V9")
        Q = self.env["stock.quant"]
        for v in tmpl.product_variant_ids:
            Q.create({"product_id": v.id, "location_id": self.loc.id, "quantity": 6.0})
        self.env.invalidate_all()
        self.assertEqual(tmpl.qty_available, 12.0)
        self.assertTrue(
            self.Tmpl.search([("id", "=", tmpl.id), ("qty_available", ">", 10)])
        )
        self.assertTrue(
            self.Tmpl.search([("id", "=", tmpl.id), ("qty_available", "=", 12)])
        )

    def test_search_still_finds_zero_stock_templates(self):
        tmpl = self.Tmpl.create({"name": "V10", "type": "consu", "is_storable": True})
        self.env.invalidate_all()
        self.assertTrue(
            self.Tmpl.search([("id", "=", tmpl.id), ("qty_available", "=", 0)]),
            "a template with no quants must still match = 0",
        )

    def test_next_serial_follows_padding_and_suffix(self):
        tmpl = self.Tmpl.create(
            {"name": "V11", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        seq = self.env["ir.sequence"].create(
            {
                "name": "V11 seq",
                "code": "stock.lot.serial",
                "prefix": "V11-",
                "padding": 3,
            }
        )
        tmpl.lot_sequence_id = seq
        self.env.invalidate_all()
        self.assertEqual(tmpl.next_serial, "V11-001")
        seq.padding = 8
        self.assertEqual(tmpl.next_serial, "V11-00000001")
        seq.suffix = "-X"
        self.assertEqual(tmpl.next_serial, "V11-00000001-X")

    def test_prefix_does_not_bind_across_companies(self):
        co_b = self.env["res.company"].create({"name": "V12 Co B"})
        t_a = self.Tmpl.create(
            {
                "name": "V12a",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
                "company_id": self.env.company.id,
            }
        )
        t_a.serial_prefix_format = "SHARED-"
        t_b = self.Tmpl.with_company(co_b).create(
            {
                "name": "V12b",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
                "company_id": co_b.id,
            }
        )
        t_b.with_company(co_b).serial_prefix_format = "SHARED-"
        self.env.invalidate_all()
        self.assertNotEqual(
            t_a.lot_sequence_id,
            t_b.lot_sequence_id,
            "each company gets its own counter",
        )
        self.assertEqual(t_a.lot_sequence_id.company_id, self.env.company)
        self.assertEqual(t_b.lot_sequence_id.company_id, co_b)
        self.assertEqual(t_a.lot_sequence_id.next_by_id(), "SHARED-0000001")
        self.assertEqual(t_b.lot_sequence_id.next_by_id(), "SHARED-0000001")

    def test_same_company_same_prefix_still_shares(self):
        a = self.Tmpl.create(
            {"name": "V13a", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        b = self.Tmpl.create(
            {"name": "V13b", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        a.serial_prefix_format = "SAME-"
        b.serial_prefix_format = "SAME-"
        self.env.invalidate_all()
        self.assertEqual(a.lot_sequence_id, b.lot_sequence_id)

    def test_action_view_quants_includes_archived_stocked_variant(self):
        tmpl = self._multi("V14")
        v_arch = tmpl.product_variant_ids[1]
        self.env["stock.quant"].create(
            {"product_id": v_arch.id, "location_id": self.loc.id, "quantity": 4.0}
        )
        self.env.cr.flush()
        v_arch.active = False
        self.env.invalidate_all()
        action = tmpl.action_view_quants()
        self.assertIn(
            v_arch.id,
            action["domain"][0][2],
            "an archived variant that still holds stock must appear",
        )

    def test_action_view_quants_drops_archived_empty_variant(self):
        tmpl = self._multi("V15")
        v_arch = tmpl.product_variant_ids[1]
        v_arch.active = False
        self.env.invalidate_all()
        action = tmpl.action_view_quants()
        self.assertNotIn(v_arch.id, action["domain"][0][2])

    def test_count_lot_ids_is_on_both_models_and_the_template_sums_its_variants(self):
        self.assertIn("count_lot_ids", self.Tmpl._fields)
        self.assertIn("count_lot_ids", self.env["product.product"]._fields)
        template = self.env["product.template"].create(
            {"name": "Lot Count Tmpl", "is_storable": True, "tracking": "lot"},
        )
        self.env["stock.lot"].create(
            [
                {"name": "LCT-1", "product_id": template.product_variant_id.id},
                {"name": "LCT-2", "product_id": template.product_variant_id.id},
            ],
        )
        self.assertEqual(template.product_variant_id.count_lot_ids, 2)
        self.assertEqual(template.count_lot_ids, 2)

    def test_action_view_routes_is_gone(self):
        self.assertFalse(hasattr(self.env["product.product"], "action_view_routes"))
        self.assertFalse(hasattr(self.Tmpl, "action_view_routes"))

    def test_create_batch_adjusts_each_product_exactly_once(self):
        Quant = self.env["stock.quant"]
        tmpls = self.Tmpl.create(
            [
                {
                    "name": f"V23-{i}",
                    "type": "consu",
                    "is_storable": True,
                    "qty_available": 2 + i,
                }
                for i in range(5)
            ]
        )
        self.env.invalidate_all()
        self.assertEqual(
            sorted(tmpls.mapped("qty_available")), [2.0, 3.0, 4.0, 5.0, 6.0]
        )
        variants = tmpls.product_variant_id
        stock_quants = Quant.search(
            [("product_id", "in", variants.ids), ("location_id", "=", self.loc.id)]
        )
        self.assertEqual(len(stock_quants), 5)
        self.assertEqual(
            sorted(stock_quants.mapped("quantity")), [2.0, 3.0, 4.0, 5.0, 6.0]
        )

    def test_create_batch_distinct_quantities_are_not_swapped(self):
        tmpls = self.Tmpl.create(
            [
                {
                    "name": f"V24-{i}",
                    "type": "consu",
                    "is_storable": True,
                    "qty_available": (i + 1) * 10,
                }
                for i in range(4)
            ]
        )
        self.env.invalidate_all()
        self.assertEqual(
            [t.qty_available for t in tmpls],
            [10.0, 20.0, 30.0, 40.0],
            "each template keeps its own quantity",
        )

    def test_create_batch_skips_nonstorable_without_shifting_others(self):
        tmpls = self.Tmpl.create(
            [
                {
                    "name": "V25a",
                    "type": "consu",
                    "is_storable": True,
                    "qty_available": 5,
                },
                {"name": "V25b", "type": "service", "qty_available": 0},
                {
                    "name": "V25c",
                    "type": "consu",
                    "is_storable": True,
                    "qty_available": 9,
                },
            ]
        )
        self.env.invalidate_all()
        self.assertEqual([t.qty_available for t in tmpls], [5.0, 0.0, 9.0])

    def test_variant_lot_action_domain_matches_template(self):
        tmpl = self.Tmpl.create({"name": "V26", "type": "consu", "is_storable": True})
        self.assertEqual(
            tmpl.action_view_product_lot()["domain"][1:],
            tmpl.product_variant_id.action_view_product_lot()["domain"][1:],
        )

    def test_move_lines_action_uses_equality(self):
        tmpl = self.Tmpl.create({"name": "V16", "type": "consu", "is_storable": True})
        self.assertEqual(
            tmpl.action_view_stock_move_lines()["domain"],
            [("product_id.product_tmpl_id", "=", tmpl.id)],
        )

    def test_lot_action_domain_shared_with_variant(self):
        tmpl = self.Tmpl.create({"name": "V17", "type": "consu", "is_storable": True})
        tmpl_domain = tmpl.action_view_product_lot()["domain"][1:]
        variant_domain = tmpl.product_variant_id.action_view_product_lot()["domain"][1:]
        self.assertEqual(tmpl_domain, variant_domain)

    def test_lot_name_format_is_on_the_product_form(self):
        view = self.env.ref("stock.view_template_property_form")
        arch = str(view.arch_db)
        self.assertIn("lot_name_format", arch)

    def test_lot_name_format_view_loads(self):
        fields = self.Tmpl.get_view(
            self.env.ref("stock.view_template_property_form").id, "form"
        )["models"]["product.template"]
        self.assertIn("lot_name_format", fields)

    def test_diagram_products_prefers_context_product(self):
        tmpl = self.Tmpl.create({"name": "V19", "type": "consu", "is_storable": True})
        other = self.Tmpl.create({"name": "V19b", "type": "consu", "is_storable": True})
        resolved = tmpl.with_context(
            default_product_id=other.product_variant_id.id
        )._get_diagram_products()
        self.assertEqual(resolved, other.product_variant_id)

    def test_diagram_products_falls_back_to_self(self):
        tmpl = self.Tmpl.create({"name": "V20", "type": "consu", "is_storable": True})
        self.assertEqual(tmpl._get_diagram_products(), tmpl.product_variant_ids)

    def test_diagram_products_falls_back_to_active_id(self):
        tmpl = self.Tmpl.create({"name": "V21", "type": "consu", "is_storable": True})
        resolved = self.Tmpl.with_context(active_id=tmpl.id)._get_diagram_products()
        self.assertEqual(resolved, tmpl.product_variant_ids)

    def test_diagram_products_ignores_empty_context_ids(self):
        tmpl = self.Tmpl.create({"name": "V22", "type": "consu", "is_storable": True})
        resolved = tmpl.with_context(default_product_id=False)._get_diagram_products()
        self.assertEqual(resolved, tmpl.product_variant_ids)

    def test_default_responsible_still_applies(self):
        self.assertTrue(self.env.user._is_superuser())
        tmpl = self.Tmpl.create({"name": "V18", "type": "consu"})
        self.assertFalse(tmpl.responsible_id, "superuser gets no responsible")

        user = self.env["res.users"].create(
            {
                "name": "V18 user",
                "login": "v18user",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("product.group_product_manager").id,
                        ],
                    )
                ],
            }
        )
        tmpl2 = self.Tmpl.with_user(user).create({"name": "V18b", "type": "consu"})
        self.assertEqual(tmpl2.responsible_id, user)


@tagged("post_install", "-at_install")
class TestProductTemplateQuantityEdgeCases(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tmpl = cls.env["product.template"]
        cls.Quant = cls.env["stock.quant"]
        cls.wh = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.loc = cls.wh.lot_stock_id

    def _two_variants(self, name):
        attr = self.env["product.attribute"].create(
            {
                "name": f"{name}-a",
                "value_ids": [(0, 0, {"name": "S"}), (0, 0, {"name": "M"})],
            }
        )
        return self.Tmpl.create(
            {
                "name": name,
                "type": "consu",
                "is_storable": True,
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": attr.id,
                            "value_ids": [(6, 0, attr.value_ids.ids)],
                        },
                    )
                ],
            }
        )

    def _set_on_hand(self, product, qty):
        self.Quant.with_context(inventory_mode=True).create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.loc.id,
                    "inventory_quantity": qty,
                }
            ]
        )._apply_inventory()

    def test_create_with_zero_quantity_does_not_crash(self):
        tmpl = self.Tmpl.create(
            {
                "name": "F01",
                "type": "consu",
                "is_storable": True,
                "qty_available": 0,
            }
        )
        self.assertEqual(tmpl.qty_available, 0.0)
        self.assertFalse(
            self.Quant.search([("product_id", "=", tmpl.product_variant_id.id)]),
            "a zero quantity must not post an adjustment",
        )

    def test_create_all_zero_batch_does_not_crash(self):
        tmpls = self.Tmpl.create(
            [
                {
                    "name": f"F02-{i}",
                    "type": "consu",
                    "is_storable": True,
                    "qty_available": 0,
                }
                for i in range(3)
            ]
        )
        self.assertEqual(len(tmpls), 3)
        self.assertEqual(tmpls.mapped("qty_available"), [0.0, 0.0, 0.0])

    def test_import_with_a_zero_quantity_column(self):
        res = self.Tmpl.load(
            ["name", "type", "is_storable", "qty_available"],
            [["F03", "consu", "1", "0"]],
        )
        self.assertFalse(res["messages"], res["messages"])
        self.assertTrue(res["ids"])

    def test_create_with_a_quantity_still_applies_it(self):
        tmpl = self.Tmpl.create(
            {
                "name": "F04",
                "type": "consu",
                "is_storable": True,
                "qty_available": 6,
            }
        )
        self.env.invalidate_all()
        self.assertEqual(tmpl.qty_available, 6.0)

    def test_ineligible_product_is_told_why_not_the_sign(self):
        service = self.Tmpl.create({"name": "F05", "type": "service"})
        with self.assertRaises(UserError) as caught:
            service.write({"qty_available": -5})
        self.assertIn("does not track inventory", str(caught.exception))

        tracked = self.Tmpl.create(
            {
                "name": "F06",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
            }
        )
        with self.assertRaises(UserError) as caught:
            tracked.write({"qty_available": -5})
        self.assertIn("lot/serial number", str(caught.exception))

    def test_negative_quantity_is_still_refused(self):
        tmpl = self.Tmpl.create({"name": "F07", "type": "consu", "is_storable": True})
        with self.assertRaises(UserError) as caught:
            tmpl.write({"qty_available": -1})
        self.assertIn("negative", str(caught.exception))

    def test_search_ignores_archived_variants_like_the_field_does(self):
        tmpl = self._two_variants("F08")
        active_variant, archived_variant = tmpl.product_variant_ids
        self._set_on_hand(active_variant, 7)
        self._set_on_hand(archived_variant, 3)
        archived_variant.active = False
        self.env.invalidate_all()

        self.assertEqual(tmpl.qty_available, 7.0)
        self.assertIn(tmpl, self.Tmpl.search([("qty_available", "=", 7)]))
        self.assertNotIn(tmpl, self.Tmpl.search([("qty_available", "=", 10)]))
        self.assertNotIn(tmpl, self.Tmpl.search([("qty_available", ">", 9)]))

    def test_search_still_matches_the_template_total(self):
        tmpl = self._two_variants("F09")
        plus, minus = tmpl.product_variant_ids
        self._set_on_hand(plus, 5)
        self._set_on_hand(minus, -5)
        self.env.invalidate_all()

        self.assertEqual(tmpl.qty_available, 0.0)
        self.assertIn(tmpl, self.Tmpl.search([("qty_available", "=", 0)]))
        self.assertNotIn(tmpl, self.Tmpl.search([("qty_available", ">", 0)]))
        self.assertNotIn(tmpl, self.Tmpl.search([("qty_available", "<", 0)]))

    def test_unsupported_operator_matches_the_template_total(self):
        tmpl = self._two_variants("F10")
        plus, minus = tmpl.product_variant_ids
        self._set_on_hand(plus, 5)
        self._set_on_hand(minus, -5)
        self.env.invalidate_all()

        domain = self.Tmpl._get_domain_variant_quantity("qty_available", "ilike", "5")
        self.assertEqual(
            [leaf[0] for leaf in domain],
            ["id"],
            "the fallback must resolve to template ids, not to product_variant_ids",
        )
        self.assertNotIn(
            tmpl.id,
            domain[0][2],
            "a template totalling 0 must not match through one of its variants",
        )

    def test_next_serial_is_the_name_the_lot_will_get(self):
        tmpl = self.Tmpl.create(
            {
                "name": "F11",
                "type": "consu",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        tmpl.serial_prefix_format = "F11-%(year)s-"
        self.env.invalidate_all()

        previewed = tmpl.next_serial
        lot = self.env["stock.lot"].create({"product_id": tmpl.product_variant_id.id})
        self.assertEqual(previewed, lot.name)
        self.assertIn("F11-", previewed)
        self.assertNotIn("%(", previewed, "the prefix must be interpolated, not raw")

    def test_prefix_change_refreshes_next_serial(self):
        tmpl = self.Tmpl.create(
            {
                "name": "F12",
                "type": "consu",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        tmpl.serial_prefix_format = "AAA-"
        self.assertTrue(tmpl.next_serial.startswith("AAA-"))
        tmpl.serial_prefix_format = "BBB-"
        self.assertTrue(tmpl.next_serial.startswith("BBB-"))

    def test_missing_standard_sequence_does_not_raise(self):
        tmpl = self.Tmpl.create(
            {
                "name": "F13",
                "type": "consu",
                "is_storable": True,
                "tracking": "serial",
            }
        )
        tmpl.lot_sequence_id = False
        self.env.flush_all()
        self.env.ref("stock.sequence_production_lots").unlink()
        self.env.transaction._ref_cache.clear()
        self.env.invalidate_all()

        tmpl.serial_prefix_format = "F13-"
        tmpl.flush_recordset()
        self.assertEqual(tmpl.lot_sequence_id.prefix, "F13-")
        self.assertEqual(tmpl.lot_sequence_id.padding, 7)

    def test_company_change_sees_archived_variants(self):
        other_company = self.env["res.company"].create({"name": "F14 co"})
        tmpl = self._two_variants("F14")
        __, archived_variant = tmpl.product_variant_ids
        self._set_on_hand(archived_variant, 4)
        archived_variant.active = False
        self.env.flush_all()

        with self.assertRaises(UserError):
            tmpl.write({"company_id": other_company.id})

    def test_show_qty_update_button_goes_through_the_overridable_method(self):
        tmpl = self.Tmpl.create({"name": "F15", "type": "consu", "is_storable": True})
        self.assertFalse(tmpl.show_qty_update_button)

        cls = type(self.Tmpl)
        original = cls._is_product_quants_open_required
        cls._is_product_quants_open_required = lambda records: True
        try:
            tmpl.invalidate_recordset()
            self.assertTrue(
                tmpl.show_qty_update_button,
                "the compute must call _is_product_quants_open_required, not restate it",
            )
        finally:
            cls._is_product_quants_open_required = original

    def test_quantity_scope_context_keys_are_in_the_cache_key(self):
        sub = self.env["stock.location"].create(
            {"name": "F16 sub", "location_id": self.loc.id, "usage": "internal"}
        )
        tmpl = self.Tmpl.create({"name": "F16", "type": "consu", "is_storable": True})
        self.Quant.with_context(inventory_mode=True).create(
            [
                {
                    "product_id": tmpl.product_variant_id.id,
                    "location_id": sub.id,
                    "inventory_quantity": 6,
                }
            ]
        )._apply_inventory()
        self.env.invalidate_all()

        scoped = tmpl.with_context(search_location=self.loc.id)
        self.assertEqual(scoped.qty_available, 6.0, "children included by default")
        self.assertEqual(
            scoped.with_context(strict=True).qty_available,
            0.0,
            "strict must not answer with the non-strict value already in cache",
        )

    def test_counts_survive_a_new_record_with_an_origin(self):
        tmpl = self.Tmpl.create({"name": "F17", "type": "consu", "is_storable": True})
        self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": tmpl.product_variant_id.id,
                "location_id": self.loc.id,
                "product_min_qty": 2,
                "product_max_qty": 9,
            }
        )
        self.env.invalidate_all()
        self.assertEqual(tmpl.count_reordering_rules, 1)

        draft = self.Tmpl.new(origin=tmpl)
        self.assertEqual(draft.count_reordering_rules, 1)
        self.assertEqual(draft.reordering_qty_max, 9.0)

    def _capacity(self, product, quantity):
        return self.env["stock.storage.category.capacity"].create(
            {
                "storage_category_id": self.category.id,
                "product_id": product.id,
                "quantity": quantity,
            }
        )

    @property
    def category(self):
        if not getattr(self, "_category", None):
            self._category = self.env["stock.storage.category"].create(
                {"name": "F-cat"}
            )
        return self._category

    def test_copy_carries_an_archived_variants_capacity(self):
        tmpl = self._two_variants("F20")
        kept, archived = tmpl.product_variant_ids
        self._capacity(kept, 10)
        self._capacity(archived, 20)
        archived.active = False
        self.env.flush_all()

        copied = tmpl.copy()
        variants = copied.with_context(active_test=False).product_variant_ids
        self.assertTrue(all(variants.mapped("active")))
        by_value = {
            capacity.product_id.product_template_attribute_value_ids.product_attribute_value_id.name: capacity.quantity
            for capacity in variants.storage_category_capacity_ids
        }
        self.assertEqual(by_value, {"S": 10.0, "M": 20.0})

    def test_copy_drops_a_capacity_with_no_counterpart(self):
        tmpl = self._two_variants("F21")
        first, second = tmpl.product_variant_ids
        self._capacity(first, 10)
        self._capacity(second, 20)
        line = tmpl.attribute_line_ids[0]
        kept_value = (
            first.product_template_attribute_value_ids.product_attribute_value_id
        )

        copied = tmpl.copy(
            {
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": line.attribute_id.id,
                            "value_ids": [(6, 0, kept_value.ids)],
                        },
                    )
                ]
            }
        )
        self.assertEqual(len(copied.product_variant_ids), 1)
        self.assertEqual(
            copied.product_variant_ids.storage_category_capacity_ids.mapped("quantity"),
            [10.0],
        )

    def test_copy_batch_keeps_each_templates_capacities_apart(self):
        first, second = self._two_variants("F22a"), self._two_variants("F22b")
        for template, quantities in ((first, (1, 2)), (second, (3, 4))):
            for variant, quantity in zip(
                template.product_variant_ids, quantities, strict=True
            ):
                self._capacity(variant, quantity)
        self.env.flush_all()

        copies = (first + second).copy()
        self.assertEqual(
            [
                sorted(
                    copy.product_variant_ids.storage_category_capacity_ids.mapped(
                        "quantity"
                    )
                )
                for copy in copies
            ],
            [[1.0, 2.0], [3.0, 4.0]],
        )

    def test_zero_adjustment_leaves_the_location_alone(self):
        tmpl = self.Tmpl.create({"name": "F18", "type": "consu", "is_storable": True})
        self.loc.last_inventory_date = False
        self.env.flush_all()

        tmpl.write({"qty_available": 0})
        self.env.flush_all()

        self.assertFalse(
            self.loc.last_inventory_date,
            "no move was posted, so no inventory happened",
        )
        self.assertFalse(
            self.env["stock.move"].search_count(
                [("product_id", "=", tmpl.product_variant_id.id)]
            ),
        )

    def test_a_real_adjustment_still_stamps_the_location(self):
        tmpl = self.Tmpl.create({"name": "F19", "type": "consu", "is_storable": True})
        self.loc.last_inventory_date = False
        self.env.flush_all()

        tmpl.write({"qty_available": 3})
        self.env.flush_all()

        self.assertTrue(self.loc.last_inventory_date)
        self.env.invalidate_all()
        self.assertEqual(tmpl.qty_available, 3.0)
