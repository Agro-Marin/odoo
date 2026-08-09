from odoo.tests import HttpCase, tagged

# Must match CATALOG_TOUR_CUSTOMER in sale/static/tests/tours/sale_catalog.js.
# The tours type this name to narrow the customer dropdown to one known record
# instead of clicking whichever entry happens to come first, so both tests have
# to create it. Without it they only passed on a database that happened to
# carry demo partners — and this fork defaults to --without-demo.
CATALOG_TOUR_CUSTOMER = "Catalog Tour Customer"


@tagged("-at_install", "post_install")
class TestSaleOrderProductCatalog(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tour_customer = cls.env["res.partner"].create(
            {"name": CATALOG_TOUR_CUSTOMER},
        )

    def test_sale_order_product_catalog_branch_company_tour(self):
        """Test adding products to a SO through the catalog view when in a branch company."""

        self.env["product.template"].create(
            {
                "name": "Restricted Product",
                "company_id": self.env.company.id,
            }
        )
        admin = self.env.ref("base.user_admin")
        branch = (
            self.env["res.company"]
            .with_user(admin)
            .create(
                {
                    "name": "Branch Company",
                    "parent_id": self.env.company.id,
                }
            )
        )
        admin.company_id = branch
        self.env["product.template"].create(
            {
                "name": "AAA Product",
                "company_id": admin.company_id.id,
            }
        )
        self.start_tour(
            "/web#action=sale.action_quotations",
            "sale_catalog",
            login="admin",
        )

    def test_add_section_from_product_catalog_on_sale_order_tour(self):
        self.env["product.template"].create(
            {"name": "Test Product", "is_favorite": True}
        )
        self.start_tour(
            "/web#action=sale.action_quotations",
            "test_add_section_from_product_catalog_on_sale_order",
            login="admin",
        )
