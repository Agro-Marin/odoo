from odoo.addons.product.tests.common import ProductCommon, ProductVariantsCommon


class TestProductDocumentCount(ProductVariantsCommon):

    def test_p1_batch_template_document_count(self):
        template1 = self.product.product_tmpl_id
        template2 = self.service_product.product_tmpl_id

        for i in range(3):
            self.env["documents.document"].create(
                {
                    "name": f"Doc {i}",
                    "res_model": "product.template",
                    "res_id": template1.id,
                }
            )

        templates = template1 | template2
        templates.invalidate_recordset(["product_document_count"])
        self.assertEqual(template1.product_document_count, 3)
        self.assertEqual(template2.product_document_count, 0)

    def test_p2_batch_product_document_count(self):
        product1 = self.product
        product2 = self.service_product

        self.env["documents.document"].create(
            {
                "name": "Variant Doc",
                "res_model": "product.product",
                "res_id": product1.id,
            }
        )

        products = product1 | product2
        products.invalidate_recordset(["product_document_count"])
        self.assertEqual(product1.product_document_count, 1)
        self.assertEqual(product2.product_document_count, 0)


class TestProductDocumentCountVariants(ProductCommon):

    def test_document_count_counts_active_variant_documents(self):
        tmpl = self.env["product.template"].create({"name": "WithDocs"})
        variant = tmpl.product_variant_ids
        self.env["documents.document"].create(
            {"name": "spec", "res_model": "product.product", "res_id": variant.id}
        )
        tmpl.invalidate_recordset(["product_document_count"])
        self.assertEqual(tmpl.product_document_count, 1)

        variant.write({"active": False})
        tmpl.invalidate_recordset(["product_document_count"])
        self.assertEqual(
            tmpl.product_document_count,
            0,
            "documents on archived variants are not counted",
        )
