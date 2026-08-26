from itertools import pairwise
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tests import Form, tagged

from odoo.addons.product.tests.common import ProductVariantsCommon


@tagged("post_install", "-at_install")
class TestPricelist(ProductVariantsCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.datacard = cls.env["product.product"].create({"name": "Office Lamp"})
        cls.usb_adapter = cls.env["product.product"].create({"name": "Office Chair"})

        cls.sale_pricelist_id, cls.pricelist_eu = cls.env["product.pricelist"].create(
            [
                {
                    "name": "Sale pricelist",
                    "item_ids": [
                        Command.create(
                            {
                                "compute_price": "formula",
                                "base": "list_price",
                                "price_discount": 10,
                                "product_id": cls.usb_adapter.id,
                                "applied_on": "0_product_variant",
                            }
                        ),
                        Command.create(
                            {
                                "compute_price": "formula",
                                "base": "list_price",
                                "price_surcharge": -0.5,
                                "product_id": cls.datacard.id,
                                "applied_on": "0_product_variant",
                            }
                        ),
                        Command.create(
                            {
                                "compute_price": "formula",
                                "base": "standard_price",
                                "price_markup": 99.99,
                                "applied_on": "3_global",
                            }
                        ),
                    ],
                },
                {
                    "name": "EU Pricelist",
                    "country_group_ids": cls.env.ref("base.europe").ids,
                },
            ]
        )

        cls.env.user.group_ids += cls.env.ref("product.group_product_pricelist")
        cls.uom_ton = cls.env.ref("uom.product_uom_ton")

    def test_10_discount(self):

        self.assertEqual(
            self.pricelist._get_product_price(self.usb_adapter, 1.0) * 0.9,
            self.sale_pricelist_id._get_product_price(self.usb_adapter, 1.0),
        )

        self.assertEqual(
            self.pricelist._get_product_price(self.datacard, 1.0) - 0.5,
            self.sale_pricelist_id._get_product_price(self.datacard, 1.0),
        )

        self.assertAlmostEqual(
            self.sale_pricelist_id._get_product_price(
                self.usb_adapter, 1.0, uom=self.uom_unit
            )
            * 12,
            self.sale_pricelist_id._get_product_price(
                self.usb_adapter, 1.0, uom=self.uom_dozen
            ),
        )

        self.assertAlmostEqual(
            self.sale_pricelist_id._get_product_price(
                self.datacard, 1.0, uom=self.uom_unit
            )
            * 12,
            self.sale_pricelist_id._get_product_price(
                self.datacard, 1.0, uom=self.uom_dozen
            ),
        )

    def test_11_markup(self):
        for item in self.sale_pricelist_id.item_ids:
            self.assertEqual(item.price_markup, -item.price_discount)

        self.sale_pricelist_id.item_ids[0].price_discount = 0
        self.sale_pricelist_id.item_ids[1].price_discount = -20.02
        self.sale_pricelist_id.item_ids[2].price_markup = -0.5
        for item in self.sale_pricelist_id.item_ids:
            self.assertEqual(item.price_markup, -item.price_discount)

    def test_20_pricelist_uom(self):

        tonne_price = 100

        spam = self.env["product.product"].create(
            {
                "name": "1 tonne of spam",
                "uom_id": self.uom_ton.id,
                "list_price": tonne_price,
                "type": "consu",
            }
        )

        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "applied_on": "0_product_variant",
                "compute_price": "formula",
                "base": "list_price",
                "min_quantity": 3,
                "price_surcharge": -10,
                "product_id": spam.id,
            }
        )

        def test_unit_price(qty, uom_id, expected_unit_price):
            uom = self.env["uom.uom"].browse(uom_id)
            unit_price = self.pricelist._get_product_price(spam, qty, uom=uom)
            self.assertAlmostEqual(
                unit_price, expected_unit_price, msg="Computed unit price is wrong"
            )

        test_unit_price(2, self.uom_kgm.id, tonne_price / 1000.0)
        test_unit_price(2000, self.uom_kgm.id, tonne_price / 1000.0)
        test_unit_price(3500, self.uom_kgm.id, (tonne_price - 10) / 1000.0)
        test_unit_price(2, self.uom_ton.id, tonne_price)
        test_unit_price(3, self.uom_ton.id, tonne_price - 10)

    def test_21_pricelist_min_quantity_near_the_rounding_floor(self):
        tonne_price = 1000.0
        bulk = self.env["product.product"].create(
            {
                "name": "1 tonne of bulk",
                "uom_id": self.uom_ton.id,
                "uom_ids": [Command.set([self.uom_ton.id, self.uom_kgm.id])],
                "list_price": tonne_price,
                "type": "consu",
            }
        )
        self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "applied_on": "0_product_variant",
                "product_id": bulk.id,
                "compute_price": "fixed",
                "fixed_price": tonne_price / 2,
                "min_quantity": 0.01,
            }
        )

        def price_per_kg(qty_kg):
            return self.pricelist._get_product_price(bulk, qty_kg, uom=self.uom_kgm)

        for qty_kg in (0.5, 1.0, 5.0, 9.9):
            with self.subTest(qty_kg=qty_kg):
                self.assertAlmostEqual(
                    price_per_kg(qty_kg),
                    tonne_price / 1000.0,
                    msg="below the tier, the list price applies",
                )
        for qty_kg in (10.0, 50.0):
            with self.subTest(qty_kg=qty_kg):
                self.assertAlmostEqual(
                    price_per_kg(qty_kg),
                    tonne_price / 2 / 1000.0,
                    msg="at or above the tier, the bulk price applies",
                )

    def test_30_pricelists_order(self):

        ProductPricelist = self.env["product.pricelist"]
        res_partner = self.env["res.partner"].create({"name": "Ready Corner"})

        ProductPricelist.search([]).active = False

        pl_first = ProductPricelist.create({"name": "First Pricelist"})
        res_partner.invalidate_recordset(["property_product_pricelist"])

        self.assertEqual(res_partner.property_product_pricelist, pl_first)

        ProductPricelist.create({"name": "Second Pricelist"})
        res_partner.invalidate_recordset(["property_product_pricelist"])

        self.assertEqual(res_partner.property_product_pricelist, pl_first)

    def test_40_specific_property_product_pricelist(self):
        pricelist_1, pricelist_2 = self.pricelist, self.sale_pricelist_id
        self.env["product.pricelist"].search(
            [
                (
                    "id",
                    "not in",
                    [pricelist_1.id, pricelist_2.id, self.pricelist_eu.id],
                ),
            ]
        ).active = False

        with Form(self.partner) as partner_form:
            partner_form.country_id = self.env.ref("base.be")
        self.assertEqual(self.partner.property_product_pricelist, self.pricelist_eu)
        self.assertFalse(self.partner.specific_property_product_pricelist)

        with Form(self.partner) as partner_form:
            partner_form.country_id = self.env.ref("base.ki")
        self.assertEqual(self.partner.property_product_pricelist, pricelist_1)
        self.assertFalse(self.partner.specific_property_product_pricelist)

        with Form(self.partner) as partner_form:
            partner_form.property_product_pricelist = pricelist_2
        self.assertEqual(self.partner.property_product_pricelist, pricelist_2)
        self.assertEqual(self.partner.specific_property_product_pricelist, pricelist_2)

        with Form(self.partner) as partner_form:
            partner_form.country_id = self.env.ref("base.be")
        self.assertEqual(self.partner.property_product_pricelist, pricelist_2)
        self.assertEqual(self.partner.specific_property_product_pricelist, pricelist_2)

    def test_45_property_product_pricelist_config_parameter(self):
        pricelist_1, pricelist_2 = self.pricelist, self.sale_pricelist_id
        self.env["product.pricelist"].search(
            [
                ("id", "not in", [pricelist_1.id, pricelist_2.id]),
            ]
        ).active = False
        self.assertEqual(self.partner.property_product_pricelist, pricelist_1)

        self.partner.invalidate_recordset(["property_product_pricelist"])
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("res.partner.property_product_pricelist", pricelist_2.id)
        with patch.object(
            self.pricelist.__class__,
            "_get_partner_pricelist_multi_search_domain_hook",
            return_value=Domain.FALSE,
        ):
            with Form(self.partner) as partner_form:
                self.assertEqual(partner_form.property_product_pricelist, pricelist_2)
                partner_form.property_product_pricelist = pricelist_1
            self.assertEqual(self.partner.property_product_pricelist, pricelist_1)
            self.assertEqual(
                self.partner.specific_property_product_pricelist, pricelist_1
            )

    def test_pricelists_multi_comp_checks(self):
        first_company = self.env.company
        second_company = self.env["res.company"].create({"name": "Test Company"})

        shared_pricelist = self.env["product.pricelist"].create(
            {
                "name": "Test Multi-comp pricelist",
                "company_id": False,
            }
        )
        second_pricelist = self.env["product.pricelist"].create(
            {
                "name": f"Second test pricelist{first_company.name}",
            }
        )

        self.assertEqual(self.pricelist.company_id, first_company)
        self.assertFalse(shared_pricelist.company_id)
        self.assertEqual(second_pricelist.company_id, first_company)

        with self.assertRaises(UserError):
            shared_pricelist.item_ids = [
                Command.create(
                    {
                        "compute_price": "formula",
                        "base": "pricelist",
                        "base_pricelist_id": self.pricelist.id,
                    }
                )
            ]

        self.pricelist.item_ids = [
            Command.create(
                {
                    "compute_price": "formula",
                    "base": "pricelist",
                    "base_pricelist_id": shared_pricelist.id,
                }
            ),
            Command.create(
                {
                    "compute_price": "formula",
                    "base": "pricelist",
                    "base_pricelist_id": second_pricelist.id,
                }
            ),
        ]

        with self.assertRaises(UserError):
            self.pricelist.company_id = second_company

    def test_pricelists_multi_comp_checks_batch_write(self):
        first_company = self.env.company
        second_company = self.env["res.company"].create({"name": "Batch Test Company"})

        base_pricelist = self.env["product.pricelist"].create(
            {
                "name": "Base pricelist (company A)",
                "company_id": first_company.id,
            }
        )
        pl_a, pl_b = self.env["product.pricelist"].create(
            [
                {
                    "name": f"Pricelist {label} (company A)",
                    "company_id": first_company.id,
                    "item_ids": [
                        Command.create(
                            {
                                "compute_price": "formula",
                                "base": "pricelist",
                                "base_pricelist_id": base_pricelist.id,
                            }
                        )
                    ],
                }
                for label in ("A", "B")
            ]
        )

        with self.assertRaises(UserError):
            (pl_a | pl_b).write({"company_id": second_company.id})

    def test_pricelists_multi_comp_checks_archived_product(self):
        first_company = self.env.company
        second_company = self.env["res.company"].create(
            {"name": "Archived Test Company"}
        )

        template = self.env["product.template"].create(
            {
                "name": "Company B product",
                "company_id": second_company.id,
            }
        )
        shared_pricelist = self.env["product.pricelist"].create(
            {
                "name": "Archived-check pricelist",
                "company_id": False,
                "item_ids": [
                    Command.create(
                        {
                            "applied_on": "1_product",
                            "product_tmpl_id": template.id,
                            "compute_price": "fixed",
                            "fixed_price": 5.0,
                        }
                    )
                ],
            }
        )

        template.action_archive()
        shared_pricelist.invalidate_recordset(["item_ids"])
        self.assertFalse(
            shared_pricelist.item_ids,
            "archived-product rule should be filtered out of item_ids",
        )

        with self.assertRaises(UserError):
            shared_pricelist.company_id = first_company

    def test_pricelists_res_partner_form(self):
        pricelist_europe = self.pricelist_eu
        default_pricelist = self.env["product.pricelist"].search(
            [("name", "ilike", " ")], limit=1
        )

        with Form(self.env["res.partner"]) as partner_form:
            partner_form.name = "test"
            self.assertEqual(partner_form.property_product_pricelist, default_pricelist)

            partner_form.country_id = self.env.ref("base.be")
            self.assertEqual(partner_form.property_product_pricelist, pricelist_europe)

            partner_form.property_product_pricelist = self.sale_pricelist_id
            self.assertEqual(
                partner_form.property_product_pricelist, self.sale_pricelist_id
            )

            partner = partner_form.save()

        with Form(partner) as partner_form:
            self.assertEqual(
                partner_form.property_product_pricelist, self.sale_pricelist_id
            )

    def test_pricelist_change_to_formula_and_back(self):
        pricelist_2 = self.env["product.pricelist"].create(
            {
                "name": "Sale pricelist 2",
                "item_ids": [
                    Command.create(
                        {
                            "compute_price": "percentage",
                            "percent_price": 20,
                            "base": "pricelist",
                            "base_pricelist_id": self.sale_pricelist_id.id,
                            "applied_on": "3_global",
                        }
                    ),
                ],
            }
        )
        with Form(pricelist_2.item_ids) as item_form:
            item_form.compute_price = "formula"
            item_form.compute_price = "percentage"
            item_form.percent_price = 20
        self.assertFalse(pricelist_2.item_ids.base_pricelist_id.id)

    def test_sync_parent_pricelist(self):
        self.partner.update(
            {
                "parent_id": False,
                "specific_property_product_pricelist": self.sale_pricelist_id.id,
            }
        )
        self.assertEqual(
            self.partner.property_product_pricelist, self.sale_pricelist_id
        )

        company_2 = self.env.company.create({"name": "Company Two"})
        company_1_b2b_pl, company_2_b2b_pl = self.sale_pricelist_id.create(
            [
                {
                    "name": f"B2B ({company.name})",
                    "company_id": company.id,
                }
                for company in self.env.company + company_2
            ]
        )
        parent = self.partner.create(
            {
                "name": f"{self.partner.name}'s Company",
                "is_company": True,
                "specific_property_product_pricelist": company_1_b2b_pl.id,
            }
        )
        parent.with_company(
            company_2
        ).specific_property_product_pricelist = company_2_b2b_pl

        self.partner.parent_id = parent
        self.assertEqual(
            self.partner.specific_property_product_pricelist,
            company_1_b2b_pl,
            "Assigning a parent with a specific pricelist should sync the parent's pricelist",
        )
        self.assertEqual(
            self.partner.with_company(company_2).specific_property_product_pricelist,
            company_2_b2b_pl,
            "Company-specific pricelists should get synced on parent assignment",
        )

        parent.specific_property_product_pricelist = self.sale_pricelist_id
        self.assertEqual(
            self.partner.specific_property_product_pricelist,
            self.sale_pricelist_id,
            "Setting a specific parent pricelist should update the partner's pricelist",
        )
        self.assertEqual(
            self.partner.with_company(company_2).specific_property_product_pricelist,
            company_2_b2b_pl,
            "Assigning pricelists in one company shouldn't impact pricelists in other companies",
        )

    def test_prevent_pricelist_recursion(self):

        def create_item_vals(pl_from, pl_to):
            return {
                "pricelist_id": pl_from.id,
                "compute_price": "formula",
                "base": "pricelist",
                "base_pricelist_id": pl_to.id,
                "applied_on": "3_global",
            }

        Pricelist = self.env["product.pricelist"]
        pl_a, pl_b, pl_c, pl_d = pricelists = Pricelist.create(
            [
                {
                    "name": f"Pricelist {c}",
                }
                for c in "ABCD"
            ]
        )

        Pricelist.item_ids.create(
            [
                create_item_vals(pl_from, pl_to)
                for (pl_from, pl_to) in pairwise(pricelists)
            ]
        )

        with self.assertRaises(ValidationError):
            Pricelist.item_ids.create(create_item_vals(pl_d, pl_d))
        with self.assertRaises(ValidationError):
            Pricelist.item_ids.create(create_item_vals(pl_d, pl_a))
        with self.assertRaises(ValidationError):
            Pricelist.item_ids.create(create_item_vals(pl_c, pl_b))

        pl_b.item_ids.unlink()
        Pricelist.item_ids.create(create_item_vals(pl_d, pl_a))
        Pricelist.item_ids.create(create_item_vals(pl_c, pl_b))

        with self.assertRaises(ValidationError):
            Pricelist.item_ids.create(create_item_vals(pl_a, pl_c))
        with self.assertRaises(ValidationError):
            Pricelist.item_ids.create(create_item_vals(pl_b, pl_d))

    def test_pricelist_rule_linked_to_product_variant(self):
        self.product_sofa_red.pricelist_rule_ids = [
            Command.create(
                {
                    "applied_on": "0_product_variant",
                    "product_id": self.product_sofa_red.id,
                    "compute_price": "fixed",
                    "fixed_price": 99.9,
                    "pricelist_id": self.pricelist.id,
                }
            ),
            Command.create(
                {
                    "applied_on": "0_product_variant",
                    "product_id": self.product_sofa_red.id,
                    "compute_price": "fixed",
                    "fixed_price": 89.9,
                    "pricelist_id": self.pricelist.id,
                }
            ),
        ]
        self.assertEqual(len(self.product_sofa_red.pricelist_rule_ids), 2)
        first_rule, second_rule = self.product_sofa_red.pricelist_rule_ids
        self.product_sofa_red.pricelist_rule_ids = [
            Command.update(first_rule.id, {"fixed_price": 79.9}),
            Command.unlink(second_rule.id),
        ]
        self.assertEqual(len(self.product_sofa_red.pricelist_rule_ids), 1)
        self.assertEqual(self.pricelist.item_ids.fixed_price, 79.9)
        self.assertIn(self.product_sofa_red, self.pricelist.item_ids.product_id)

        self.product_template_sofa.pricelist_rule_ids = [
            Command.create(
                {
                    "applied_on": "1_product",
                    "product_tmpl_id": self.product_template_sofa.id,
                    "pricelist_id": self.pricelist.id,
                }
            ),
            Command.create(
                {
                    "applied_on": "0_product_variant",
                    "product_id": self.product_sofa_blue.id,
                    "compute_price": "fixed",
                    "fixed_price": 89.9,
                    "pricelist_id": self.pricelist.id,
                }
            ),
        ]
        self.assertEqual(len(self.product_template_sofa.pricelist_rule_ids), 3)
        template_rule = self.product_template_sofa.pricelist_rule_ids.filtered(
            lambda item: not item.product_id
        )
        self.assertEqual(len(self.product_sofa_red.pricelist_rule_ids), 2)
        self.product_sofa_red.pricelist_rule_ids = [
            Command.update(template_rule.id, {"fixed_price": 133}),
        ]
        self.assertEqual(template_rule.fixed_price, 133)

        self.product_sofa_red.pricelist_rule_ids = [
            Command.unlink(template_rule.id),
        ]
        self.assertFalse(template_rule.exists())

        self.assertTrue(self.product_sofa_blue.pricelist_rule_ids)
        self.assertEqual(len(self.product_template_sofa.pricelist_rule_ids), 2)

    def test_pricelist_applied_on_product_variant(self):
        sofa_1 = self.product_template_sofa.product_variant_ids[0]
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "Pricelist for Acoustic Bloc Screens",
                "item_ids": [
                    Command.create(
                        {
                            "compute_price": "fixed",
                            "fixed_price": 123,
                            "base": "list_price",
                            "applied_on": "1_product",
                            "product_tmpl_id": self.product_template_sofa.id,
                        }
                    ),
                ],
            }
        )
        with Form(pricelist.item_ids) as item_form:
            item_form.product_id = sofa_1
        self.assertEqual(pricelist.item_ids.applied_on, "0_product_variant")
        with Form(pricelist.item_ids) as item_form:
            item_form.product_id = self.env["product.product"]
        self.assertEqual(pricelist.item_ids.applied_on, "1_product")
        self.assertFalse(pricelist.item_ids.product_id)
