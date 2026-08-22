from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductTemplateFollowupFixes(TransactionCase):
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

        domain = self.Tmpl._search_variant_quantity("qty_available", "ilike", "5")
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
        original = cls._should_open_product_quants
        cls._should_open_product_quants = lambda records: True
        try:
            tmpl.invalidate_recordset()
            self.assertTrue(
                tmpl.show_qty_update_button,
                "the compute must call _should_open_product_quants, not restate it",
            )
        finally:
            cls._should_open_product_quants = original


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
