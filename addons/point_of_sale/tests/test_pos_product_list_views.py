from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPosProductListViews(TransactionCase):
    """Which product list carries the POS columns.

    A field in a list arch is an entry in the optional-columns dropdown, so
    every POS field added to the generic product list is one more line every
    salesperson has to read past.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env["product.template"]

    def _fields_of(self, xml_id):
        arch = self.Template.get_view(self.env.ref(xml_id).id, "list")["arch"]
        return {node.get("name") for node in etree.fromstring(arch).iter("field")}

    def test_the_sales_product_list_carries_no_pos_columns(self):
        """Selling a product does not mean configuring a register."""
        fields = self._fields_of("product.view_product_template_list")
        self.assertNotIn("pos_categ_ids", fields)
        self.assertNotIn("available_in_pos", fields)

    def test_the_pos_product_list_carries_them(self):
        """The register's own product list is where they belong."""
        fields = self._fields_of(
            "point_of_sale.view_product_template_list_point_of_sale"
        )
        self.assertIn("pos_categ_ids", fields)
        self.assertIn("available_in_pos", fields)
        self.assertIn("pos_sequence", fields)

    def test_self_ordering_extends_the_pos_list_and_not_the_sales_one(self):
        """`self_order_available` follows `available_in_pos`, wherever it went."""
        if "self_order_available" not in self.Template._fields:
            self.skipTest("pos_self_order is not installed")
        self.assertNotIn(
            "self_order_available",
            self._fields_of("product.view_product_template_list"),
        )
        self.assertIn(
            "self_order_available",
            self._fields_of("point_of_sale.view_product_template_list_point_of_sale"),
        )
