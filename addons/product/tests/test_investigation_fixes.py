from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCompanyDefaultPricelistCurrency(TransactionCase):
    """The auto-created "Default" pricelist must follow its company's currency.

    `_activate_or_create_pricelists` recognises that pricelist by
    `currency_id == company_id.currency_id`. When a company changed currency the
    pricelist kept the old one, so the next activation no longer recognised it
    and created a *second* pricelist named "Default" for the same company.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids = [
            (4, cls.env.ref("product.group_product_pricelist").id),
        ]
        cls.usd = cls.env.ref("base.USD")
        cls.eur = cls.env.ref("base.EUR")
        cls.eur.sudo().active = True

    def _default_pricelists(self, company):
        return (
            self.env["product.pricelist"]
            .sudo()
            .with_context(active_test=False)
            .search([("company_id", "=", company.id)])
        )

    def test_default_pricelist_follows_company_currency(self):
        company = self.env["res.company"].create(
            {"name": "PL Currency Co", "currency_id": self.usd.id},
        )
        pricelists = self._default_pricelists(company)
        self.assertEqual(len(pricelists), 1)
        self.assertEqual(pricelists.currency_id, self.usd)

        company.write({"currency_id": self.eur.id})

        pricelists = self._default_pricelists(company)
        self.assertEqual(len(pricelists), 1, "no second pricelist should appear")
        self.assertEqual(
            pricelists.currency_id,
            self.eur,
            "the rule-less default pricelist must follow the company currency",
        )

    def test_no_duplicate_default_pricelist_after_currency_change(self):
        company = self.env["res.company"].create(
            {"name": "PL Dup Co", "currency_id": self.usd.id},
        )
        company.write({"currency_id": self.eur.id})

        # Verbatim the call `res_config_settings.set_values` (re-enabling the
        # Pricelists setting) and `res_currency._activate_group_multi_currency`
        # (activating a second currency) make -- on the *empty* recordset, so
        # it sweeps every company. That is what turns the drift into a second
        # pricelist named "Default"; `res.company.create` does not, because it
        # only ever passes the companies it just created.
        self.env["res.company"]._activate_or_create_pricelists()

        pricelists = self._default_pricelists(company)
        self.assertEqual(
            len(pricelists),
            1,
            "a company must not end up with two pricelists named 'Default'",
        )

    def _configured_pricelist(self, company, product):
        return (
            self.env["product.pricelist"]
            .sudo()
            .create(
                {
                    "name": "Export USD",
                    "company_id": company.id,
                    "currency_id": self.usd.id,
                    "item_ids": [
                        (
                            0,
                            0,
                            {
                                "product_tmpl_id": product.id,
                                "compute_price": "fixed",
                                "fixed_price": 10.0,
                            },
                        ),
                    ],
                },
            )
        )

    def test_configured_pricelist_currency_is_left_alone(self):
        """A pricelist that carries rules is a business decision, not a default."""
        company = self.env["res.company"].create(
            {"name": "PL Configured Co", "currency_id": self.usd.id},
        )
        product = self.env["product.template"].create(
            {"name": "Configured Product", "company_id": company.id},
        )
        configured = self._configured_pricelist(company, product)

        company.write({"currency_id": self.eur.id})

        self.assertEqual(configured.currency_id, self.usd)

    def test_configured_pricelist_on_archived_products_is_left_alone(self):
        """The rules must be counted directly, not through `item_ids`.

        `item_ids` carries a domain hiding rules whose product is archived, so
        a fully configured pricelist reads as rule-less and its currency would
        be rewritten -- silently re-denominating every `fixed_price` on it.
        """
        company = self.env["res.company"].create(
            {"name": "PL Archived Co", "currency_id": self.usd.id},
        )
        product = self.env["product.template"].create(
            {"name": "Archived Product", "company_id": company.id},
        )
        configured = self._configured_pricelist(company, product)
        product.active = False
        self.env.invalidate_all()

        # The trap this guards against, asserted so the test cannot silently
        # stop exercising it: the pricelist still has its rule, yet the
        # `item_ids = False` lookup the old code used matches it.
        self.assertTrue(
            self.env["product.pricelist.item"]
            .sudo()
            .search_count([("pricelist_id", "=", configured.id)]),
            "the rules are still there",
        )
        self.assertIn(
            configured,
            self.env["product.pricelist"]
            .sudo()
            .with_context(active_test=False)
            .search([("item_ids", "=", False), ("company_id", "=", company.id)]),
            "`item_ids = False` is expected to mis-match a pricelist whose rules"
            " all target archived products",
        )

        company.write({"currency_id": self.eur.id})

        self.assertEqual(
            configured.currency_id,
            self.usd,
            "a pricelist with rules must never be re-denominated",
        )


@tagged("post_install", "-at_install")
class TestCatalogContextContract(TransactionCase):
    def test_catalog_action_carries_the_order_id_the_client_reads(self):
        """`kanban_model.js`/`kanban_controller.js` read `context.order_id`.

        It used to exist only because every caller's button repeated
        `context="{'order_id': parent.id}"`; a caller that followed the mixin's
        docstring got a catalog with no quantities and no error.
        """
        context = self.env[
            "mixin.product.catalog"
        ]._get_action_add_from_catalog_extra_context()

        self.assertIn("order_id", context)
        # One key, not two: `product_catalog_order_id` used to carry the same id
        # for the half of the client that read that name instead.
        self.assertNotIn("product_catalog_order_id", context)

    def test_action_context_reaches_the_client_with_order_id(self):
        """End to end: no button context, yet the action still carries it."""
        order_model = self.env.registry.get("sale.order")
        if order_model is None:
            self.skipTest("sale not installed")
        order = self.env["sale.order"].create(
            {"partner_id": self.env.ref("base.partner_admin").id},
        )

        action = order.action_add_from_catalog()

        self.assertEqual(action["context"]["order_id"], order.id)
        self.assertEqual(action["context"]["product_catalog_order_model"], "sale.order")


@tagged("post_install", "-at_install")
class TestSectionSearchInputValidation(TransactionCase):
    """`product_catalog_order_model` / `child_field` arrive from the client.

    They are forwarded verbatim from the catalog kanban's search context, so an
    unknown model or field name has to fail like the catalog controller does,
    not as a bare KeyError out of `search()`.
    """

    def _search(self, **ctx):
        return (
            self.env["product.product"]
            .with_context(**ctx)
            .search(
                [("is_in_selected_section_of_order", "=", True)],
            )
        )

    def test_unknown_model_is_rejected(self):
        with self.assertRaises(UserError):
            self._search(
                order_id=1,
                product_catalog_order_model="not.a.model",
                child_field="line_ids",
            )

    def test_model_without_the_catalog_mixin_is_rejected(self):
        with self.assertRaises(UserError):
            self._search(
                order_id=1,
                product_catalog_order_model="res.partner",
                child_field="child_ids",
            )

    def test_unknown_line_field_is_rejected(self):
        with self.assertRaises(UserError):
            self._search(
                order_id=1,
                product_catalog_order_model="mixin.product.catalog",
                child_field="no_such_field",
            )

    def test_incomplete_context_is_not_an_error(self):
        """Nothing to filter by: the domain stays open, as before."""
        self.assertTrue(self._search(order_id=1) or True)


@tagged("post_install", "-at_install")
class TestPackagingCompanyConsistency(TransactionCase):
    """`product.uom` must not name a product of another company.

    It is the same shape as `product.combo.item` -- own `company_id`, own
    multi-company record rule, readable by every employee -- and that model
    already enforces it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        currency = cls.env.ref("base.USD")
        cls.company_a, cls.company_b = cls.env["res.company"].create(
            [
                {"name": "Packaging Co A", "currency_id": currency.id},
                {"name": "Packaging Co B", "currency_id": currency.id},
            ],
        )
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")

    def _product(self, company):
        return (
            self.env["product.template"]
            .create(
                {"name": "Packaging Product", "company_id": company.id},
            )
            .product_variant_id
        )

    def test_cross_company_packaging_is_rejected(self):
        product_b = self._product(self.company_b)
        # `_check_company` raises UserError, not ValidationError.
        with self.assertRaises(UserError):
            self.env["product.uom"].create(
                {
                    "company_id": self.company_a.id,
                    "product_id": product_b.id,
                    "uom_id": self.uom_unit.id,
                    "barcode": "PKG-XCOMPANY",
                },
            )

    def test_same_company_packaging_is_allowed(self):
        product_a = self._product(self.company_a)
        packaging = self.env["product.uom"].create(
            {
                "company_id": self.company_a.id,
                "product_id": product_a.id,
                "uom_id": self.uom_unit.id,
                "barcode": "PKG-SAMECOMPANY",
            },
        )
        self.assertEqual(packaging.company_id, self.company_a)

    def test_packaging_for_a_shared_product_is_allowed(self):
        """A product with no company belongs to every company."""
        shared = (
            self.env["product.template"]
            .create(
                {"name": "Shared Packaging Product"},
            )
            .product_variant_id
        )
        packaging = self.env["product.uom"].create(
            {
                "company_id": self.company_a.id,
                "product_id": shared.id,
                "uom_id": self.uom_unit.id,
                "barcode": "PKG-SHARED",
            },
        )
        self.assertFalse(packaging.product_id.company_id)

    def test_cross_company_packaging_defeats_the_barcode_check(self):
        """Why the constraint matters: it is what keeps barcodes unique.

        Both sides of the product/packaging barcode check scope by company, so
        a packaging filed under company A for a product of company B is
        invisible to company B's check -- and B may then reuse the barcode.
        The row is created in SQL because the constraint now refuses it; this
        reproduces the state a database could already be in.
        """
        product_b = self._product(self.company_b)
        self.env.cr.execute(
            """
            INSERT INTO product_uom (barcode, company_id, product_id, uom_id,
                                     create_uid, write_uid, create_date, write_date)
            VALUES ('PKG-BARCODE-CLASH', %s, %s, %s, 1, 1, now(), now())
            """,
            (self.company_a.id, product_b.id, self.uom_unit.id),
        )
        self.env.invalidate_all()

        colliding = self._product(self.company_b)
        colliding.barcode = "PKG-BARCODE-CLASH"
        self.assertEqual(
            colliding.barcode,
            "PKG-BARCODE-CLASH",
            "the cross-company packaging is invisible to company B's check --"
            " which is exactly what `check_company` now prevents from arising",
        )

        # Control: the same packaging inside company B is caught.
        self.env.cr.execute(
            """
            INSERT INTO product_uom (barcode, company_id, product_id, uom_id,
                                     create_uid, write_uid, create_date, write_date)
            VALUES ('PKG-BARCODE-SAME', %s, %s, %s, 1, 1, now(), now())
            """,
            (self.company_b.id, product_b.id, self.uom_unit.id),
        )
        self.env.invalidate_all()
        with self.assertRaises(ValidationError):
            self._product(self.company_b).barcode = "PKG-BARCODE-SAME"


@tagged("post_install", "-at_install")
class TestPricelistUnknownBase(TransactionCase):
    """A `base` the rule cannot compute from must say so, not KeyError.

    `base` is a Selection, so `create`/`write` cannot store an unknown value;
    a column left behind by an uninstalled module that extended the selection
    can. The old bare `else` passed it to `product._compute_price`, which reads
    it as a field name.
    """

    def test_unknown_base_raises_a_readable_error(self):
        template = self.env["product.template"].create(
            {"name": "Unknown Base Product", "list_price": 100.0},
        )
        pricelist = self.env["product.pricelist"].create({"name": "Unknown Base PL"})
        rule = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "product_tmpl_id": template.id,
                "compute_price": "formula",
                "base": "list_price",
                "price_discount": 10.0,
            },
        )
        self.assertEqual(
            pricelist._get_product_price(template.product_variant_id, 1.0), 90.0
        )

        self.env.cr.execute(
            "UPDATE product_pricelist_item SET base = 'bogus' WHERE id = %s",
            (rule.id,),
        )
        self.env.invalidate_all()

        with self.assertRaises(ValidationError):
            pricelist._get_product_price(template.product_variant_id, 1.0)


@tagged("post_install", "-at_install")
class TestLabelLayoutMissingWizard(TransactionCase):
    def test_missing_layout_wizard_is_a_user_error(self):
        """The wizard is transient: `data` can name one that is already gone."""
        from odoo.addons.product.report.product_label_report import _prepare_data

        with self.assertRaises(UserError):
            _prepare_data(
                self.env,
                [],
                {"active_model": "product.template", "layout_wizard": 0},
            )


@tagged("post_install", "-at_install")
class TestTransientWizardIsolation(TransactionCase):
    """Both product wizards are TransientModels, so neither is isolated by default."""

    def test_every_product_wizard_has_an_ownership_rule(self):
        wizards = [
            "product.label.layout",
            "update.product.attribute.value",
        ]
        for model in wizards:
            with self.subTest(model=model):
                rules = (
                    self.env["ir.rule"].sudo().search([("model_id.model", "=", model)])
                )
                self.assertTrue(
                    rules,
                    f"{model} is a TransientModel reachable by id and has no"
                    " record rule scoping it to its creator",
                )
                self.assertIn("create_uid", "".join(rules.mapped("domain_force")))


@tagged("post_install", "-at_install")
class TestCatalogPricePortalTarget(TransactionCase):
    """The catalog card must keep the node `ProductCatalogOrderLine` portals into.

    `order_line.xml` renders the price through
    `t-portal="`#product-${props.productId}-price`"`, and that target is an empty
    div declared in the *view arch*, not anywhere in JS. OWL does not degrade
    when a portal target is missing -- it raises `invalid portal target` from
    `onMounted`, which takes down the whole kanban rather than one card, and the
    message names neither the view nor the component.

    Nothing else checks this: the coupling crosses from a `.xml` view record to a
    `.js` component, so no linter or asset gate sees both ends. An inheriting
    view that xpath-removes or renames the node is exactly how it would be lost.
    """

    def test_catalog_card_declares_the_price_portal_target(self):
        arch = self.env.ref("product.view_product_product_kanban_catalog").arch_db

        self.assertIn(
            "product-{{record.id.raw_value}}-price",
            arch,
            "product.view_product_product_kanban_catalog must keep the element "
            "ProductCatalogOrderLine portals its price into; without it every "
            "catalog card raises OwlError: invalid portal target.",
        )

    def test_the_order_line_still_addresses_that_target(self):
        """The other end of the pair, so the test cannot silently outlive it."""
        import pathlib

        import odoo.addons.product as product_module

        order_line = (
            pathlib.Path(product_module.__file__).parent
            / "static/src/product_catalog/order_line/order_line.xml"
        )

        self.assertIn(
            "-price`",
            order_line.read_text(),
            f"{order_line} no longer portals into an id ending in '-price'; if "
            "the price is rendered some other way now, drop this pair of tests "
            "and the arch node they guard.",
        )
