"""Regression pins for the product.template stock follow-up audit (2026-08-13).

Every test here fails on the commit before this one. They are separate from
``test_audit_fixes_product_template`` because three of them pin defects that the
*previous* audit's implementation introduced, and keeping the two batches apart keeps
that attribution readable.
"""

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

    # ------------------------------------------------------------------ create

    def test_create_with_zero_quantity_does_not_crash(self):
        """The inverse used to run before the variants existed and die on a zip().

        `qty_available` is withheld from `super()` on the presence of the key, not on
        the truth of its value, so this reaches `_set_qty_available` as a no-op.
        """
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
        """The bug was batch-shaped: one non-zero row masked it for the whole batch."""
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
        """`load()` is how a user meets this: a spreadsheet with an On Hand column."""
        res = self.Tmpl.load(
            ["name", "type", "is_storable", "qty_available"],
            [["F03", "consu", "1", "0"]],
        )
        self.assertFalse(res["messages"], res["messages"])
        self.assertTrue(res["ids"])

    def test_create_with_a_quantity_still_applies_it(self):
        """The withholding must not swallow a real quantity."""
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

    # ------------------------------------------------------- validation order

    def test_ineligible_product_is_told_why_not_the_sign(self):
        """Sign-first told a service product to make its quantity non-negative."""
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

    # -------------------------------------------------------------- searching

    def test_search_ignores_archived_variants_like_the_field_does(self):
        """The field sums active variants; the candidate set carried archived ones."""
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
        """The previous batch's fix must survive the archived-variant scoping."""
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
        """The fallback used to revert to `any variant matches`.

        Driven through `_search_variant_quantity` directly: `Domain` rejects these
        operators on a Float before the search hook is reached, so the branch has no
        route in from `search()` -- which is exactly why it could hold the abolished
        semantics unnoticed. What is pinned is that it resolves against templates, not
        against variants.
        """
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

    # ------------------------------------------------------------- next_serial

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

        # Read before the lot exists: `preview_next` reports the number the sequence
        # will hand out next, and creating the lot consumes it.
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
        """Deleting the sequence is not refused, and used to break every save."""
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

    # ------------------------------------------------------------- company move

    def test_company_change_sees_archived_variants(self):
        """An archived variant keeps its quants; the guard was scoped to active ones."""
        other_company = self.env["res.company"].create({"name": "F14 co"})
        tmpl = self._two_variants("F14")
        __, archived_variant = tmpl.product_variant_ids
        self._set_on_hand(archived_variant, 4)
        archived_variant.active = False
        self.env.flush_all()

        with self.assertRaises(UserError):
            tmpl.write({"company_id": other_company.id})

    # ---------------------------------------------------------- overridability

    def test_show_qty_update_button_goes_through_the_overridable_method(self):
        """Inlining the rule dropped mrp's kit override; nothing caught it.

        Asserted against an override installed on the fly so the pin holds whether or
        not `mrp` is in the addons path.
        """
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

    # --------------------------------------------------------------- scoping

    def test_quantity_scope_context_keys_are_in_the_cache_key(self):
        """`strict` narrows to the exact location; it must not reuse the wide answer."""
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
        """`self.ids` resolves a NewId to its origin; the lookup keyed by `.id` did not."""
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

    # ---------------------------------------------------- no-op adjustment

    def test_zero_adjustment_leaves_the_location_alone(self):
        """Re-saving a product already at 0 is not an inventory count.

        The zero-difference quant itself still gets written -- that is how every
        inventory-mode adjustment starts, and a quant at 0 is vacuumed like any other.
        What must not happen is the whole-location bookkeeping: `_apply_inventory`
        already suppresses the *move* for this case, and the date stamp has to agree
        with it.
        """
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
