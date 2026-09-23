from odoo.addons.document_compliance.tests.common import ComplianceCase


class TestComplianceReportProducts(ComplianceCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["document.type"].search([("is_mandatory", "=", True)]).write(
            {"is_mandatory": False}
        )
        cls.pesticides = cls.env["product.category"].create({"name": "Pesticides"})
        cls.fungicides = cls.env["product.category"].create(
            {"name": "Fungicides", "parent_id": cls.pesticides.id}
        )
        cls.packaging = cls.env["product.category"].create({"name": "Packaging"})
        cls.fungicide = cls.env["product.template"].create(
            {"name": "Reported Fungicide", "categ_id": cls.fungicides.id}
        )
        cls.drum = cls.env["product.template"].create(
            {"name": "Reported Drum", "categ_id": cls.packaging.id}
        )

    def _row(self, product):
        self._publish()
        return self.env["document.compliance.report"].search(
            [("entity_type", "=", "product.template"), ("entity_id", "=", product.id)]
        )

    def test_products_are_an_entity_a_type_can_apply_to(self):
        selection = dict(self.env["document.type"]._selection_applies_to())

        self.assertIn("product.template", selection)

    def test_a_product_with_a_valid_registration_is_compliant(self):
        registration = self._type(
            "SCOPE_PRODUCT", is_mandatory=True, applies_to="product.template"
        )
        self._doc(
            registration,
            365,
            name="Sanitary Registration",
            res_model="product.template",
            res_id=self.fungicide.id,
        )

        row = self._row(self.fungicide)

        self.assertEqual(row.entity_name, "Reported Fungicide")
        self.assertEqual((row.total_required, row.total_valid), (1, 1))
        self.assertEqual(row.compliance_state, "compliant")

    def test_a_missing_or_expired_registration_is_reported(self):
        registration = self._type(
            "SCOPE_PRODUCT", is_mandatory=True, applies_to="product.template"
        )
        self._doc(
            registration,
            -1,
            name="Lapsed Registration",
            res_model="product.template",
            res_id=self.fungicide.id,
        )

        self.assertEqual(self._row(self.fungicide).total_expired, 1)
        self.assertEqual(self._row(self.drum).total_missing, 1)

    def test_types_for_every_entity_do_not_reach_products(self):
        self._type("SCOPE_ALL", is_mandatory=True, applies_to="all")

        self.assertFalse(self._row(self.fungicide))

    def test_a_category_scope_covers_its_subcategories_only(self):
        self._type(
            "SCOPE_PESTICIDES",
            is_mandatory=True,
            applies_to="product.template",
            product_categ_ids=[(6, 0, self.pesticides.ids)],
        )

        self.assertEqual(self._row(self.fungicide).total_required, 1)
        self.assertFalse(self._row(self.drum))
