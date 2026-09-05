from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.product.tests.common import ProductCommon


@tagged("post_install", "-at_install")
class TestProductCategoryCompany(ProductCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env["res.company"].create({"name": "Categ Company A"})
        cls.company_b = cls.env["res.company"].create({"name": "Categ Company B"})
        cls.company_child_a = cls.env["res.company"].create(
            {"name": "Categ Company A Child", "parent_id": cls.company_a.id}
        )
        cls.categ_a = cls.env["product.category"].create(
            {"name": "Only A", "company_id": cls.company_a.id}
        )
        cls.categ_shared = cls.env["product.category"].create({"name": "Shared"})

    def test_shared_category_accepts_any_company(self):
        for company in (self.company_a, self.company_b, self.env["res.company"]):
            product = self.env["product.template"].create(
                {
                    "name": "Shared categ product",
                    "categ_id": self.categ_shared.id,
                    "company_id": company.id,
                }
            )
            self.assertEqual(product.categ_id, self.categ_shared)

    def test_restricted_category_refuses_a_foreign_company_product(self):
        # check_company is enforced by the framework, which raises UserError
        # (ValidationError's superclass), not by our own @api.constrains.
        with self.assertRaises(UserError):
            self.env["product.template"].create(
                {
                    "name": "Foreign",
                    "categ_id": self.categ_a.id,
                    "company_id": self.company_b.id,
                }
            )

    def test_restricted_category_refuses_a_shared_product(self):
        with self.assertRaises(UserError):
            self.env["product.template"].create(
                {
                    "name": "Shared product, restricted categ",
                    "categ_id": self.categ_a.id,
                    "company_id": False,
                }
            )

    def test_restricted_category_accepts_a_child_company_product(self):
        # This fork runs product.template on check_company_domain_parent_of, so a
        # child company's product may use its parent company's category.  The
        # semantics come from the co-record's model, hence the same override on
        # product.category.
        product = self.env["product.template"].create(
            {
                "name": "Child company product",
                "categ_id": self.categ_a.id,
                "company_id": self.company_child_a.id,
            }
        )
        self.assertEqual(product.categ_id, self.categ_a)

    def test_cannot_restrict_a_category_that_holds_foreign_products(self):
        self.env["product.template"].create(
            {
                "name": "Company B product",
                "categ_id": self.categ_shared.id,
                "company_id": self.company_b.id,
            }
        )
        with self.assertRaises(ValidationError):
            self.categ_shared.company_id = self.company_a

    def test_pricelist_rule_category_is_company_checked(self):
        pricelist = self.env["product.pricelist"].create(
            {"name": "B pricelist", "company_id": self.company_b.id}
        )
        with self.assertRaises(UserError):
            self.env["product.pricelist.item"].create(
                {
                    "pricelist_id": pricelist.id,
                    "applied_on": "2_product_category",
                    "categ_id": self.categ_a.id,
                    "company_id": self.company_b.id,
                }
            )

    def test_record_rule_hides_a_foreign_category(self):
        user_b = self.env["res.users"].create(
            {
                "name": "Categ user B",
                "login": "categ_user_b",
                "company_id": self.company_b.id,
                "company_ids": [self.company_b.id],
                "group_ids": [self.quick_ref("product.group_product_manager").id],
            }
        )
        visible = self.env["product.category"].with_user(user_b).search([])
        self.assertNotIn(self.categ_a, visible)
        self.assertIn(self.categ_shared, visible)
