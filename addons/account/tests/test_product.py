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
        """Internal users need read access to products, no matter their taxes."""
        # Add a tag to product_a's default tax
        tax_line_tag = self.env["account.account.tag"].create(
            {
                "name": "Tax tag",
                "applicability": "taxes",
            }
        )
        self.product_a.taxes_id.repartition_line_ids.tag_ids = tax_line_tag
        # Check that internal user can read product_a
        self.env.invalidate_all()
        with Form(self.product_a.with_user(self.internal_user)) as form_a:
            # The tax string itself is not very important here; we just check
            # it has a value and we can read it, so there were no access errors
            self.assertTrue(form_a.tax_string)

    def test_multi_company_product_tax(self):
        """Ensure default taxes are set for all companies on products with no company set."""
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
        # Product should have all the default taxes of the other companies.
        self.assertRecordValues(
            product_without_company.sudo(),
            [
                {
                    "taxes_id": companies.account_sale_tax_id.ids,
                    "supplier_taxes_id": companies.account_purchase_tax_id.ids,
                }
            ],
        )  # Take care that inactive default taxes won't be shown on the product
        # Product should have only the default tax of the company it belongs to.
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
        """Ensure that setting a tax on a product overrides the default tax of branch companies."""
        parent_company = self.env.company
        # Branches share taxes with their parent company, so the branch default
        # would otherwise leak onto the parent company's product.
        # Create a branch company and set a default sales tax.
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

        # Create a product in the parent company and set its sales tax to the new tax
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
        """A public price with sub-cent precision under a price-included tax rounds
        to that price instead of collapsing to the tax-excluded base."""
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
        # A raw ``price == total_included`` float comparison would send
        # ``1234.567`` (total_included rounds to ``1234.57``) down the
        # tax-excluded branch and return the excluded base (~``1064``).
        for price, expected in [(1234.567, 1234.57), (100.005, 100.01), (100.0, 100.0)]:
            self.assertEqual(
                currency.compare_amounts(product._get_list_price(price), expected),
                0,
                f"_get_list_price({price}) with a price-included tax should round"
                " to the input price",
            )

    def test_get_list_price_price_excluded_tax(self):
        """With a price-excluded tax, the list price is the tax-excluded base of the
        tax-inclusive public price."""
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
        # 121.0 tax-inclusive public price -> 100.0 tax-excluded base at 21%.
        self.assertEqual(
            product.currency_id.compare_amounts(product._get_list_price(121.0), 100.0),
            0,
        )

    def test_retrieve_product_by_identifiers(self):
        """``_retrieve_product`` matches by barcode, default_code and exact name,
        and returns an empty recordset when nothing matches."""
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
        """Two plan entries sharing a priority must not crash the sort."""
        # The plan holds ``(priority, bound_method)`` tuples and bound methods are
        # not orderable, so sorting on the whole tuple would raise once priorities
        # tie: ``_retrieve_product`` must sort on the priority alone.
        Product = self.env["product.product"]
        product = Product.create({"name": "ZZ Collision Probe"})
        original_plan = Product._get_retrieval_product_search_plan

        def colliding_plan(self):
            # Reuse the barcode entry's priority (5) to force a tie.
            return original_plan() + [
                (5, self._import_retrieve_product_from_default_code)
            ]

        with patch.object(
            type(Product), "_get_retrieval_product_search_plan", colliding_plan
        ):
            # Must not raise; still resolves by exact name.
            self.assertEqual(
                Product._retrieve_product(name="ZZ Collision Probe"), product
            )

    def test_retrieve_product_extra_domain(self):
        """``extra_domain`` narrows the search rather than being silently
        ignored: a domain that excludes the only match yields nothing, and one
        that keeps it still returns it."""
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
        """Fuzzy name retrieval returns the closest candidate, not merely the
        first one over the threshold that happens to sort earlier."""
        Product = self.env["product.product"]
        # Both contain "ZZ Widget" (so both pass the ``ilike`` prefilter) and
        # neither equals the query exactly (so the exact-name criterion does not
        # short-circuit). "ZZ Widget X" sorts first but is the weaker match.
        Product.create({"name": "ZZ Widget X"})  # ratio ~0.90, sorts first
        best = Product.create({"name": "ZZ Widgets"})  # ratio ~0.95
        self.env["ir.config_parameter"].sudo().set_param(
            "account.product_name_similarity_threshold", "0.5"
        )
        self.assertEqual(Product._retrieve_product(name="ZZ Widget"), best)

    def test_get_product_accounts_requires_single_record(self):
        """``_get_product_accounts`` raises on a multi-record call."""
        # Account resolution is per-product: without the guard, a multi-record
        # call would silently return one product's accounts for the whole set.
        products = self.product_a + self.product_b
        with self.assertRaises(ValueError):
            products._get_product_accounts()

    def test_import_product_classification_domain_inert_without_codes(self):
        """The classification hook contributes nothing when no code is supplied,
        so plain retrieval is unaffected."""
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
