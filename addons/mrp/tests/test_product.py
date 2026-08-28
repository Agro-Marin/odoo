from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestMrpProductKitQuantities(TestMrpCommon):
    """`product.product._prepare_quantities_vals`, the kit branch."""

    def _make_kit(self, bom_qty, line_qty, on_hand):
        component, kit = self.env["product.product"].create(
            [
                {"name": "Kit component", "is_storable": True},
                {"name": "Kit", "is_storable": True},
            ]
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": bom_qty,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create(
                        {"product_id": component.id, "product_qty": line_qty}
                    ),
                ],
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, on_hand
        )
        self.env.invalidate_all()
        return component, kit

    def test_kit_availability_keeps_the_kits_of_a_partial_bom(self):
        """A ratio of BoMs is not a quantity, so it must not be rounded.

        201 components at 200 per BoM is 1.005 BoMs; each BoM yields 1000 kits,
        so 1005 kits are available. Flooring the ratio at the 'Product Unit'
        precision first threw away every kit the partial BoM would have made.
        """
        __, kit = self._make_kit(bom_qty=1000.0, line_qty=200.0, on_hand=201.0)
        self.assertEqual(kit.qty_available, 1005.0)
        self.assertEqual(kit.qty_free, 1005.0)
        self.assertEqual(kit.qty_available_virtual, 1005.0)

    def test_kit_availability_at_an_ordinary_bom_scale(self):
        """The 201-of-200 example is not the only shape that loses kits.

        Any BoM whose `product_qty` is large enough that the truncated fraction
        of a BoM is worth a whole kit loses them -- here one component at 3 per
        BoM for a BoM of 99 kits: 1/3 of a BoM is 33 kits, and flooring the
        ratio at two decimals threw away 1 of them. Across 300 randomised kits
        the two implementations disagreed on 29, and the new one matched exact
        arithmetic on all 300.
        """
        __, kit = self._make_kit(bom_qty=99.0, line_qty=3.0, on_hand=1.0)
        self.assertEqual(kit.qty_available, 33.0)

    def test_kit_availability_survives_a_zero_decimal_product_unit(self):
        """Same defect, reached through the precision instead of the scale."""
        self.env["decimal.precision"].search([("name", "=", "Product Unit")]).digits = 0
        self.env.registry.clear_cache()
        __, kit = self._make_kit(bom_qty=2.0, line_qty=2.0, on_hand=3.0)
        self.assertEqual(kit.qty_available, 3.0)

    def test_kit_availability_is_still_whole_kits(self):
        """Dropping the ratio rounding must not start reporting half a kit."""
        __, kit = self._make_kit(bom_qty=1.0, line_qty=2.0, on_hand=3.0)
        self.assertEqual(kit.qty_available, 1.0)

    def test_kit_with_no_storable_component_has_no_availability(self):
        component, kit = self.env["product.product"].create(
            [
                {"name": "Kit service", "type": "service"},
                {"name": "Kit", "is_storable": True},
            ]
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
            }
        )
        self.env.invalidate_all()
        self.assertEqual(kit.qty_available, 0.0)
        self.assertEqual(kit.qty_available_virtual, 0.0)

    def test_two_kits_sharing_a_component_read_it_once(self):
        """The context memo is what keeps the component read from squaring."""
        component = self.env["product.product"].create(
            {"name": "Shared component", "is_storable": True}
        )
        kits = self.env["product.product"].create(
            [
                {"name": "Kit A", "is_storable": True},
                {"name": "Kit B", "is_storable": True},
            ]
        )
        for kit in kits:
            self.env["mrp.bom"].create(
                {
                    "product_tmpl_id": kit.product_tmpl_id.id,
                    "product_qty": 1.0,
                    "type": "phantom",
                    "bom_line_ids": [
                        Command.create({"product_id": component.id, "product_qty": 1})
                    ],
                }
            )
        self.env["stock.quant"]._update_available_quantity(
            component, self.stock_location, 4.0
        )
        self.env.invalidate_all()
        self.assertEqual(kits.mapped("qty_available"), [4.0, 4.0])


@tagged("post_install", "-at_install")
class TestMrpProductIsKits(TestMrpCommon):
    """`is_kit` and everything else that asks "does this product explode"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "Kit Co B"})
        cls.env.user.company_ids = [Command.link(cls.company_b.id)]
        cls.component, cls.kit = cls.env["product.product"].create(
            [
                {"name": "B component", "is_storable": True},
                {"name": "B kit", "is_storable": True},
            ]
        )
        cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "company_id": cls.company_b.id,
                "bom_line_ids": [
                    Command.create({"product_id": cls.component.id, "product_qty": 1})
                ],
            }
        )

    def _in_both_companies(self, model):
        return self.env[model].with_context(
            allowed_company_ids=[self.company_a.id, self.company_b.id]
        )

    def test_search_is_kit_agrees_with_the_field(self):
        """`search` scoped to `env.companies`, the field to `env.company`.

        A list filtered on `is_kit = False` therefore hid rows whose own cell
        read False, and `mrp_account`'s valuation domain excluded products that
        are not kits for the company doing the valuation.
        """
        for model, record in (
            ("product.product", self.kit),
            ("product.template", self.kit.product_tmpl_id),
        ):
            with self.subTest(model=model):
                scoped = self._in_both_companies(model)
                self.assertFalse(scoped.browse(record.id).is_kit)
                self.assertNotIn(record.id, scoped.search([("is_kit", "=", True)]).ids)
                self.assertIn(record.id, scoped.search([("is_kit", "=", False)]).ids)

    def test_search_is_kit_finds_the_kit_in_its_own_company(self):
        for model, record in (
            ("product.product", self.kit),
            ("product.template", self.kit.product_tmpl_id),
        ):
            with self.subTest(model=model):
                scoped = self.env[model].with_company(self.company_b)
                self.assertTrue(scoped.browse(record.id).is_kit)
                self.assertIn(record.id, scoped.search([("is_kit", "=", True)]).ids)
                self.assertNotIn(record.id, scoped.search([("is_kit", "=", False)]).ids)

    def test_search_is_kit_refuses_what_it_cannot_answer(self):
        """The fork's guard shape, reached only through `determine_domain`.

        A real domain never gets here with a mixed value: `('is_kit', 'in',
        [True, False])` is collapsed to TRUE by `_optimize_boolean_in_all`
        before any search method runs, and `= False` arrives as `not in [True]`,
        which the operator check already refuses so the ORM can invert the
        positive answer. Measured, all four spellings. So this pins the
        convention (`stock_location._search_is_empty`), not a reachable
        defect.
        """
        for model in ("product.product", "product.template"):
            with self.subTest(model=model):
                field = self.env[model]._fields["is_kit"]
                self.assertIs(
                    field.determine_domain(self.env[model], "in", [True, False]),
                    NotImplemented,
                )

    def _stock_both_companies(self):
        """5 components where company A can see them, 7 where company B can."""
        warehouse_b = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_b.id)], limit=1
        )
        Quant = self.env["stock.quant"]
        Quant._update_available_quantity(self.component, self.stock_location, 5.0)
        Quant.with_company(self.company_b)._update_available_quantity(
            self.component, warehouse_b.lot_stock_id, 7.0
        )
        self.env.invalidate_all()

    def test_an_archived_kit_bom_is_not_a_kit_under_active_test_false(self):
        """`active` is stated in the domain, not left to `active_test`.

        `_bom_find` refuses an archived BoM outright, so the field and the
        search must too -- whatever context the caller reads them in. Left to
        `active_test`, the search returned a product whose only phantom BoM was
        archived while the field and `_bom_find` both said no.
        """
        by_template, by_variant = self.env["product.product"].create(
            [
                {"name": "Archived kit, template BoM", "is_storable": True},
                {"name": "Archived kit, variant BoM", "is_storable": True},
            ]
        )
        # Both halves of the search: a BoM for every variant of the template,
        # and one pinned to a single variant. The parent stated `active` on the
        # first query and not on the second, so only the variant-pinned BoM
        # leaked -- a test that builds just a template BoM passes either way.
        self.env["mrp.bom"].create(
            [
                {
                    "product_tmpl_id": by_template.product_tmpl_id.id,
                    "product_qty": 1.0,
                    "type": "phantom",
                    "active": False,
                    "bom_line_ids": [
                        Command.create(
                            {"product_id": self.component.id, "product_qty": 1}
                        )
                    ],
                },
                {
                    "product_tmpl_id": by_variant.product_tmpl_id.id,
                    "product_id": by_variant.id,
                    "product_qty": 1.0,
                    "type": "phantom",
                    "active": False,
                    "bom_line_ids": [
                        Command.create(
                            {"product_id": self.component.id, "product_qty": 1}
                        )
                    ],
                },
            ]
        )
        for record in (by_template, by_variant):
            for model, res_id in (
                ("product.product", record.id),
                ("product.template", record.product_tmpl_id.id),
            ):
                for active_test in (True, False):
                    with self.subTest(
                        product=record.name, model=model, active_test=active_test
                    ):
                        scoped = self.env[model].with_context(active_test=active_test)
                        self.assertFalse(scoped.browse(res_id).is_kit)
                        self.assertNotIn(
                            res_id, scoped.search([("is_kit", "=", True)]).ids
                        )

    def test_kit_quantities_are_scoped_to_the_active_company(self):
        """The quantity path used to explode a BoM of any company at all.

        A product whose `is_kit` cell read False on the very form reported its
        components' availability instead of its own: company A read 5 -- its
        own view of a component it does not consume -- where the product holds
        no stock of its own at all.
        """
        self._stock_both_companies()
        self.assertEqual(self.kit.with_company(self.company_a).qty_available, 0.0)
        self.assertEqual(self.kit.with_company(self.company_b).qty_available, 7.0)

    def test_quantity_search_scoped_to_the_active_company(self):
        self._stock_both_companies()
        Product = self.env["product.product"]
        self.assertNotIn(
            self.kit.id,
            Product.with_company(self.company_a)
            .search([("qty_available", ">", 0)])
            .ids,
        )
        self.assertIn(
            self.kit.id,
            Product.with_company(self.company_b)
            .search([("qty_available", ">", 0)])
            .ids,
        )


@tagged("post_install", "-at_install")
class TestMrpProductActions(TestMrpCommon):
    def test_action_view_bom_on_an_empty_recordset(self):
        """`self.ids[0]` on an empty recordset raised IndexError.

        Defensive: the smart button always carries a record, so this is not a
        path a user reaches today. It costs one conditional and turns a
        traceback into an empty action for any caller that does.
        """
        for model in ("product.product",):
            action = self.env[model].browse().action_view_bom()
            self.assertFalse(action["context"]["default_product_tmpl_id"])
            self.assertFalse(action["context"]["default_product_id"])

    def test_archiving_a_component_warns_once_for_both_models(self):
        component = self.env["product.product"].create(
            {"name": "Still used", "is_storable": True}
        )
        finished = self.env["product.product"].create(
            {"name": "Finished", "is_storable": True}
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
            }
        )
        for record in (component, component.product_tmpl_id):
            with self.subTest(model=record._name):
                record.action_unarchive()
                action = record.action_archive()
                self.assertEqual(action["tag"], "display_notification")
                self.assertIn("Still used", action["params"]["title"])

    def test_archiving_an_unused_product_keeps_the_super_result(self):
        product = self.env["product.product"].create(
            {"name": "Unused", "is_storable": True}
        )
        self.assertNotEqual(
            (product.action_archive() or {}).get("tag"), "display_notification"
        )


@tagged("post_install", "-at_install")
class TestMrpProductRoutes(TestMrpCommon):
    def test_manufacture_route_follows_the_variant_that_has_the_bom(self):
        """`product.bom_ids` is the *template's* o2m.

        A variant with no BoM of its own claimed the Manufacture route from a
        sibling variant's BoM. Both consumers use this dict only as a
        memoisation key, so no rule set moves with it -- an orderpoint on the
        BoM-less sibling resolves to `['manufacture']` either way, from the
        warehouse. This pins the dict's own contract.
        """
        attribute = self.env["product.attribute"].create(
            {
                "name": "Size",
                "value_ids": [
                    Command.create({"name": "S"}),
                    Command.create({"name": "L"}),
                ],
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "Sized",
                "is_storable": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        small, large = template.product_variant_ids
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": template.id,
                "product_id": small.id,
                "product_qty": 1.0,
                "type": "normal",
            }
        )
        routes = (small | large)._get_total_routes_by_product()
        manufacture = (
            self.env["stock.rule"].search([("action", "=", "manufacture")]).route_id
        )
        self.assertTrue(manufacture & routes[small.id])
        self.assertFalse(manufacture & routes[large.id])

    def test_a_kit_only_product_gets_no_manufacture_route(self):
        kit = self.env["product.product"].create({"name": "Kit", "is_storable": True})
        component = self.env["product.product"].create(
            {"name": "Component", "is_storable": True}
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
            }
        )
        manufacture = (
            self.env["stock.rule"].search([("action", "=", "manufacture")]).route_id
        )
        self.assertFalse(manufacture & kit._get_total_routes_by_product()[kit.id])


@tagged("post_install", "-at_install")
class TestMrpProductUpdateUom(TestMrpCommon):
    """`_update_uom` -- every mrp model that stamps a unit beside a quantity."""

    def _make_bom(self, finished, byproduct, component):
        return self.env["mrp.bom"].create(
            {
                "product_tmpl_id": finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "normal",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
                "byproduct_ids": [
                    Command.create({"product_id": byproduct.id, "product_qty": 1})
                ],
            }
        )

    def test_changing_a_uom_restamps_byproducts_and_unbuilds(self):
        finished, byproduct, component = self.env["product.product"].create(
            [
                {"name": "Finished", "is_storable": True},
                {"name": "Byproduct", "is_storable": True},
                {"name": "Component", "is_storable": True},
            ]
        )
        bom = self._make_bom(finished, byproduct, component)
        unbuild = self.env["mrp.unbuild"].create(
            {"product_id": finished.id, "bom_id": bom.id, "product_qty": 1}
        )

        byproduct.product_tmpl_id.uom_id = self.uom_dozen
        finished.product_tmpl_id.uom_id = self.uom_dozen
        self.env.invalidate_all()

        self.assertEqual(
            bom.byproduct_ids.product_uom_id,
            self.uom_dozen,
            "a byproduct line left on the old unit reinterprets its quantity",
        )
        self.assertEqual(unbuild.product_uom_id, self.uom_dozen)

    def test_a_per_unit_workcenter_capacity_does_not_block_a_uom_change(self):
        """`mrp.workcenter.capacity` must stay out of the restamp table.

        Its `product_uom_id` is the unit the capacity is *rated* in, not a stamp
        of the product's own: `_get_capacity` ranks `(product, caller's unit)`
        explicitly and the UNIQUE index is
        `(workcenter_id, product_id, product_uom_id)`, so several rows per
        product in different units are a supported configuration. Restamping
        them made `_restamp_uom`'s guard refuse the product's unit change for
        exactly that configuration.
        """
        workcenter = self.env["mrp.workcenter"].create({"name": "Capacity WC"})
        product = self.env["product.product"].create(
            {"name": "Rated in two units", "is_storable": True}
        )
        self.env["mrp.workcenter.capacity"].create(
            [
                {
                    "workcenter_id": workcenter.id,
                    "product_id": product.id,
                    "product_uom_id": self.uom_unit.id,
                    "capacity": 10,
                },
                {
                    "workcenter_id": workcenter.id,
                    "product_id": product.id,
                    "product_uom_id": self.uom_dozen.id,
                    "capacity": 2,
                },
            ]
        )
        product.product_tmpl_id.uom_id = self.uom_dozen
        self.env.flush_all()
        self.assertEqual(
            sorted(
                workcenter.capacity_ids.filtered(
                    lambda c: c.product_id == product
                ).mapped("capacity")
            ),
            [2.0, 10.0],
            "the rated capacities must survive the product's unit change",
        )

    def test_changing_a_uom_is_refused_when_a_byproduct_used_another(self):
        finished, byproduct, component = self.env["product.product"].create(
            [
                {"name": "Finished", "is_storable": True},
                {"name": "Byproduct", "is_storable": True},
                {"name": "Component", "is_storable": True},
            ]
        )
        bom = self._make_bom(finished, byproduct, component)
        bom.byproduct_ids.product_uom_id = self.uom_dozen
        with self.assertRaises(UserError):
            byproduct.product_tmpl_id.uom_id = self.uom_kg


@tagged("post_install", "-at_install")
class TestMrpProductKitDomainIsOne(TestMrpCommon):
    """`mrp.bom._get_kit_domain` is the only spelling of "this explodes"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.component = cls.env["product.product"].create(
            {"name": "Kit component", "is_storable": True}
        )

    def _make_kit(self, name, **bom_vals):
        kit = self.env["product.product"].create({"name": name, "is_storable": True})
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create({"product_id": self.component.id, "product_qty": 1})
                ],
                **bom_vals,
            }
        )
        return kit

    def test_a_reordering_rule_is_refused_on_a_live_kit_only(self):
        """The orderpoint constraint spelled the kit domain a fourth time.

        Its copy stated no `active`, which is a no-op under the default context
        -- `search_count` filters archived rows itself -- and a defect under
        `active_test=False`, which is how the second half of this reads it: an
        archived phantom BoM refused a reordering rule nothing would ever
        explode past.
        """
        live = self._make_kit("Live kit")
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        vals = {
            "location_id": warehouse.lot_stock_id.id,
            "product_min_qty": 5,
            "product_max_qty": 10,
        }
        with self.assertRaises(ValidationError):
            Orderpoint.create(dict(vals, product_id=live.id))
        for active_test in (True, False):
            with self.subTest(active_test=active_test):
                # A fresh product each pass: the orderpoint is unique per
                # (product, location, company).
                archived = self._make_kit(f"Archived kit {active_test}", active=False)
                scoped = Orderpoint.with_context(active_test=active_test)
                self.assertTrue(
                    scoped.create(dict(vals, product_id=archived.id)),
                    "an archived kit BoM must not refuse a reordering rule",
                )

    def test_phantom_bom_products_agree_with_the_field(self):
        """`_get_phantom_bom_products` reads through `is_kit`, not its own scan.

        What it replaced loaded every kit BoM in the database as records and
        expanded the template-level ones through `product_variant_ids`, with a
        company scope of its own.
        """
        live = self._make_kit("Live kit")
        archived = self._make_kit("Archived kit", active=False)
        kits = self.env["product.product"]._get_phantom_bom_products()
        self.assertIn(live, kits)
        self.assertNotIn(archived, kits)
        self.assertNotIn(self.component, kits)
        self.assertEqual(
            kits, self.env["product.product"].search([("is_kit", "=", True)])
        )


@tagged("post_install", "-at_install")
class TestMrpProductQuantityScope(TestMrpCommon):
    """The kit branch honours the scope it is *handed*, not just the context."""

    def test_kit_quantities_use_the_location_domains_argument(self):
        """`_prepare_quantities_vals(location_domains=...)` reached the kit.

        The kit branch read `component.qty_available`, which goes back through
        `_compute_quantities` and rebuilds the scope from the context -- so an
        argument a caller passed was dropped on the floor. Every caller derives
        it from the same context today, which is why nothing caught it; this
        hands the two apart on purpose.
        """
        from odoo.addons.stock.models.product_product import QuantityFilters

        component, kit = self.env["product.product"].create(
            [
                {"name": "Scoped component", "is_storable": True},
                {"name": "Scoped kit", "is_storable": True},
            ]
        )
        self.env["mrp.bom"].create(
            {
                "product_tmpl_id": kit.product_tmpl_id.id,
                "product_qty": 1.0,
                "type": "phantom",
                "bom_line_ids": [
                    Command.create({"product_id": component.id, "product_qty": 1})
                ],
            }
        )
        elsewhere = self.env["stock.location"].create(
            {
                "name": "Scoped elsewhere",
                "usage": "internal",
                "location_id": self.warehouse_1.view_location_id.id,
            }
        )
        self.env["stock.quant"]._update_available_quantity(component, elsewhere, 7.0)
        self.env.invalidate_all()

        Location = self.env["stock.location"]
        in_stock = Location.with_context(
            location=self.stock_location.id
        )._quantity_domains_from_context()
        in_elsewhere = Location.with_context(
            location=elsewhere.id
        )._quantity_domains_from_context()

        # The context says "the whole warehouse"; the argument says otherwise.
        scoped = kit.with_context(mrp_compute_quantities={})
        self.assertEqual(
            scoped._prepare_quantities_vals(
                QuantityFilters(), location_domains=in_elsewhere
            )[kit.id]["qty_available"],
            7.0,
        )
        scoped = kit.with_context(mrp_compute_quantities={})
        self.assertEqual(
            scoped._prepare_quantities_vals(
                QuantityFilters(), location_domains=in_stock
            )[kit.id]["qty_available"],
            0.0,
            "the kit must be read in the scope it was handed",
        )


@tagged("post_install", "-at_install")
class TestMrpProductMixin(TestMrpCommon):
    """`mixin.mrp.product` -- one body, two models, one token apart."""

    def test_both_models_carry_the_mixin_and_declare_their_field(self):
        for model, product_field, bom_field in (
            ("product.template", "product_tmpl_id", "bom_ids"),
            ("product.product", "product_id", "variant_bom_ids"),
        ):
            with self.subTest(model=model):
                records = self.env[model]
                # `_inherit` reads back resolved, so the class attributes and
                # the MRO are what say the mixin is in.
                self.assertEqual(records._mrp_product_field, product_field)
                self.assertEqual(records._mrp_bom_field, bom_field)
                self.assertIn(
                    "MixinMrpProduct",
                    [owner.__name__ for owner in type(records).__mro__],
                )

    def test_the_shared_bodies_are_defined_once(self):
        cls = type(self.env["product.product"])
        for name in (
            "_compute_used_in_bom_count",
            "action_used_in_bom",
            "action_view_mos",
            "write",
            "_get_still_used_bom_lines",
            "_get_backend_root_menu_ids",
        ):
            with self.subTest(method=name):
                owners = [
                    owner.__module__
                    for owner in cls.__mro__
                    if name in owner.__dict__ and ".mrp." in owner.__module__
                ]
                self.assertEqual(
                    owners,
                    ["odoo.addons.mrp.models.mixin_mrp_product"],
                    "mrp must define this once, on the mixin",
                )

    def test_action_view_mos_is_scoped_to_the_right_product_field(self):
        product = self.env["product.product"].create(
            {"name": "Viewed", "is_storable": True}
        )
        variant_action = product.action_view_mos()
        template_action = product.product_tmpl_id.action_view_mos()
        self.assertIn(("product_id", "in", product.ids), variant_action["domain"][1][2])
        self.assertIn(
            ("product_tmpl_id", "in", product.product_tmpl_id.ids),
            template_action["domain"][1][2],
        )

    def test_archiving_a_product_archives_only_its_own_boms(self):
        """`_mrp_bom_field` is the whole difference between the two overrides.

        Two variants on purpose: archiving the only variant of a template
        archives the template too (`product.product.action_archive`), which
        would archive `bom_ids` for a reason that has nothing to do with this.
        """
        attribute = self.env["product.attribute"].create(
            {
                "name": "Archive size",
                "value_ids": [
                    Command.create({"name": "S"}),
                    Command.create({"name": "L"}),
                ],
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "Archivable",
                "is_storable": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        variant = template.product_variant_ids[0]
        template_bom = self.env["mrp.bom"].create(
            {"product_tmpl_id": template.id, "product_qty": 1.0, "type": "normal"}
        )
        variant_bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": template.id,
                "product_id": variant.id,
                "product_qty": 1.0,
                "type": "normal",
            }
        )
        variant.action_archive()
        self.assertTrue(
            template_bom.active, "the variant owns `variant_bom_ids`, not `bom_ids`"
        )
        self.assertFalse(variant_bom.active)
        variant.action_unarchive()
        template.action_archive()
        self.assertFalse(template_bom.active)
