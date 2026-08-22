from unittest.mock import patch

from odoo.tests import Form, tagged
from odoo.tests.common import new_test_user

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "post_install_l10n", "-at_install")
class TestProduct(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal_user = new_test_user(
            cls.env,
            login="internal_user",
            groups="base.group_user",
        )
        cls.account_manager_user = new_test_user(
            cls.env,
            login="account_manager_user",
            groups="account.group_account_manager",
        )

    def test_internal_user_can_read_product_with_tax_and_tags(self):
        tax_line_tag = self.env["account.account.tag"].create(
            {
                "name": "Tax tag",
                "applicability": "taxes",
            }
        )
        self.product_a.taxes_id.repartition_line_ids.tag_ids = tax_line_tag
        self.env.invalidate_all()
        with Form(self.product_a.with_user(self.internal_user)) as form_a:
            self.assertTrue(form_a.tax_string)

    def test_multi_company_product_tax(self):
        product_without_company = (
            self.env["product.template"]
            .with_context(allowed_company_ids=self.env.company.ids)
            .create(
                {
                    "name": "Product Without a Company",
                }
            )
        )
        product_with_company = (
            self.env["product.template"]
            .with_context(allowed_company_ids=self.env.company.ids)
            .create(
                {
                    "name": "Product With a Company",
                    "company_id": self.company_data["company"].id,
                }
            )
        )
        companies = self.env["res.company"].sudo().search([])
        self.assertRecordValues(
            product_without_company.sudo(),
            [
                {
                    "taxes_id": companies.account_sale_tax_id.ids,
                    "supplier_taxes_id": companies.account_purchase_tax_id.ids,
                }
            ],
        )
        self.assertRecordValues(
            product_with_company.sudo(),
            [
                {
                    "taxes_id": self.company_data["company"].account_sale_tax_id.ids,
                    "supplier_taxes_id": self.company_data[
                        "company"
                    ].account_purchase_tax_id.ids,
                }
            ],
        )

    def test_product_tax_with_company_and_branch(self):
        parent_company = self.env.company
        self.env["res.company"].create(
            {
                "name": "Branch Company",
                "parent_id": parent_company.id,
                "account_sale_tax_id": parent_company.account_sale_tax_id.id,
            }
        )

        tax_new = self.env["account.tax"].create(
            {
                "name": "tax_new",
                "amount_type": "percent",
                "amount": 21.0,
                "type_tax_use": "sale",
            }
        )

        product = (
            self.env["product.template"]
            .with_context(allowed_company_ids=[parent_company.id])
            .create(
                {
                    "name": "Product with new Tax",
                    "taxes_id": tax_new.ids,
                }
            )
        )

        self.assertEqual(
            product.taxes_id,
            tax_new,
            "The branch company default tax shouldn't be set if we set a different tax on the product from the parent company.",
        )

    def test_get_list_price_price_included_tax_subcent(self):
        tax_incl = self.env["account.tax"].create(
            {
                "name": "16% included",
                "amount": 16.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "price_include_override": "tax_included",
            }
        )
        product = self.env["product.template"].create(
            {"name": "Sub-cent priced", "taxes_id": tax_incl.ids}
        )
        currency = product.currency_id
        for price, expected in [(1234.567, 1234.57), (100.005, 100.01), (100.0, 100.0)]:
            self.assertEqual(
                currency.compare_amounts(product._get_list_price(price), expected),
                0,
                f"_get_list_price({price}) with a price-included tax should round"
                " to the input price",
            )

    def test_get_list_price_price_excluded_tax(self):
        tax_excl = self.env["account.tax"].create(
            {
                "name": "21% excluded",
                "amount": 21.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
                "price_include_override": "tax_excluded",
            }
        )
        product = self.env["product.template"].create(
            {"name": "Excl priced", "taxes_id": tax_excl.ids}
        )
        self.assertEqual(
            product.currency_id.compare_amounts(product._get_list_price(121.0), 100.0),
            0,
        )

    def test_retrieve_product_by_identifiers(self):
        Product = self.env["product.product"]
        product = Product.create(
            {
                "name": "ZZ Retrieval Probe",
                "default_code": "RET-PROBE-001",
                "barcode": "0000000012345",
            }
        )
        self.assertEqual(Product._retrieve_product(barcode="0000000012345"), product)
        self.assertEqual(
            Product._retrieve_product(default_code="RET-PROBE-001"), product
        )
        self.assertEqual(Product._retrieve_product(name="ZZ Retrieval Probe"), product)
        self.assertFalse(Product._retrieve_product(barcode="NO-SUCH-BARCODE"))

    def test_retrieve_product_search_plan_priority_collision(self):
        Product = self.env["product.product"]
        product = Product.create({"name": "ZZ Collision Probe"})
        original_plan = Product._get_retrieval_product_search_plan

        def colliding_plan(self):
            return original_plan() + [
                (5, self._import_retrieve_product_from_default_code)
            ]

        with patch.object(
            type(Product), "_get_retrieval_product_search_plan", colliding_plan
        ):
            self.assertEqual(
                Product._retrieve_product(name="ZZ Collision Probe"), product
            )

    def test_retrieve_product_extra_domain(self):
        Product = self.env["product.product"]
        product = Product.create(
            {"name": "ZZ Extra Domain Probe", "default_code": "RET-EXTRA-1"}
        )
        self.assertFalse(
            Product._retrieve_product(
                default_code="RET-EXTRA-1", extra_domain=[("id", "=", -1)]
            ),
            "extra_domain excluding the match must suppress it",
        )
        self.assertEqual(
            Product._retrieve_product(
                default_code="RET-EXTRA-1", extra_domain=[("id", "=", product.id)]
            ),
            product,
        )

    def test_retrieve_product_by_name_returns_best_match(self):
        Product = self.env["product.product"]
        Product.create({"name": "ZZ Widget X"})
        best = Product.create({"name": "ZZ Widgets"})
        self.env["ir.config_parameter"].sudo().set_param(
            "account.product_name_similarity_threshold", "0.5"
        )
        self.assertEqual(Product._retrieve_product(name="ZZ Widget"), best)

    def test_get_product_accounts_requires_single_record(self):
        products = self.product_a + self.product_b
        with self.assertRaises(ValueError):
            products._get_product_accounts()

    def test_import_product_classification_domain_inert_without_codes(self):
        Product = self.env["product.product"]
        self.assertEqual(
            Product._get_import_product_classification_domain({"name": "x"}),
            ([], []),
        )
        self.assertTrue(
            all(
                value is None
                for value in Product._get_import_product_cache_discriminators(
                    {"name": "x"}
                ).values()
            )
        )
