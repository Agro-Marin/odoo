"""Regression pins for the product.template stock audit fixes (2026-08-12)."""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductTemplateAuditFixes(TransactionCase):
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
        """A Form save sends 0.0; that must stay harmless."""
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

    def test_count_lot_ids_removed_from_template(self):
        """Unreferenced on the template. Still live on product.product, which has
        its own compute, its own @api.depends and a test pinning invalidation."""
        self.assertNotIn("count_lot_ids", self.Tmpl._fields)
        self.assertIn("count_lot_ids", self.env["product.product"]._fields)

    def test_action_view_routes_is_gone(self):
        """It called a product.template method that never existed."""
        self.assertFalse(hasattr(self.env["product.product"], "action_view_routes"))
        self.assertFalse(hasattr(self.Tmpl, "action_view_routes"))

    def test_create_batch_adjusts_each_product_exactly_once(self):
        """One stock quant per product -- no duplicate adjustment from the batch path.

        ``_apply_inventory`` also writes a counterpart quant at the adjustment
        location, so the total is two per product; only the stock-location one is
        the adjustment itself.
        """
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
        """A zero-quantity service in the middle must not misalign the rest."""
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
        )._resolve_diagram_products()
        self.assertEqual(resolved, other.product_variant_id)

    def test_diagram_products_falls_back_to_self(self):
        tmpl = self.Tmpl.create({"name": "V20", "type": "consu", "is_storable": True})
        self.assertEqual(tmpl._resolve_diagram_products(), tmpl.product_variant_ids)

    def test_diagram_products_falls_back_to_active_id(self):
        tmpl = self.Tmpl.create({"name": "V21", "type": "consu", "is_storable": True})
        resolved = self.Tmpl.with_context(active_id=tmpl.id)._resolve_diagram_products()
        self.assertEqual(resolved, tmpl.product_variant_ids)

    def test_diagram_products_ignores_empty_context_ids(self):
        """A stale default_product_id must not shadow self."""
        tmpl = self.Tmpl.create({"name": "V22", "type": "consu", "is_storable": True})
        resolved = tmpl.with_context(
            default_product_id=False
        )._resolve_diagram_products()
        self.assertEqual(resolved, tmpl.product_variant_ids)

    def test_default_responsible_still_applies(self):
        """String-name default must behave exactly like the old lambda."""
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
