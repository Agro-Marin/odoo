from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductBarcode(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["product.product"].create(
            [
                {"name": "BC1", "barcode": "1"},
                {"name": "BC2", "barcode": "2"},
            ]
        )

        cls.size_attribute = cls.env["product.attribute"].create(
            {
                "name": "Size",
                "value_ids": [
                    Command.create({"name": "SMALL"}),
                    Command.create({"name": "LARGE"}),
                ],
            }
        )
        cls.size_attribute_s, cls.size_attribute_l = cls.size_attribute.value_ids

        cls.template = cls.env["product.template"].create({"name": "template"})
        cls.template.write(
            {
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": cls.size_attribute.id,
                            "value_ids": [
                                Command.link(cls.size_attribute_s.id),
                                Command.link(cls.size_attribute_l.id),
                            ],
                        }
                    )
                ]
            }
        )

    def test_blank_barcodes_allowed(self):
        for i in range(2):
            self.env["product.product"].create({"name": f"BC_{i}"})

    def test_false_barcodes_allowed(self):
        for i in range(2):
            self.env["product.product"].create({"name": f"BC_{i}", "barcode": False})

    def test_duplicated_barcode(self):
        with self.assertRaises(ValidationError):
            self.env["product.product"].create({"name": "BC3", "barcode": "1"})

    def test_duplicated_barcode_in_batch_edit(self):
        batch = [
            {"name": "BC3", "barcode": "3"},
            {"name": "BC4", "barcode": "4"},
        ]
        self.env["product.product"].create(batch)
        batch.append({"name": "BC5", "barcode": "1"})
        with self.assertRaises(ValidationError):
            self.env["product.product"].create(batch)

    def test_test_duplicated_barcode_error_msg_content(self):
        batch = [
            {"name": "BC3", "barcode": "3"},
            {"name": "BC4", "barcode": "3"},
            {"name": "BC5", "barcode": "4"},
            {"name": "BC6", "barcode": "4"},
            {"name": "BC7", "barcode": "1"},
        ]
        with self.assertRaises(ValidationError) as capture:
            self.env["product.product"].create(batch)
        message = capture.exception.args[0]
        self.assertIn(
            'Barcode "3" already assigned to product(s): BC3 and BC4', message
        )
        self.assertIn(
            'Barcode "4" already assigned to product(s): BC5 and BC6', message
        )
        self.assertIn('Barcode "1" already assigned to product(s): BC1', message)

    def test_delete_packaging_and_use_its_barcode_in_product(self):
        pack_uom = self.env["uom.uom"].create(
            {
                "name": "Pack of 10",
                "relative_factor": 10,
                "relative_uom_id": self.env.ref("uom.product_uom_unit").id,
            }
        )
        product = self.env["product.product"].create(
            {
                "name": "product",
                "uom_ids": [Command.link(pack_uom.id)],
            }
        )
        packaging_barcode = self.env["product.uom"].create(
            {
                "barcode": "1234",
                "product_id": product.id,
                "uom_id": pack_uom.id,
            }
        )
        packaging = product.product_uom_ids
        self.assertTrue(packaging.exists())
        self.assertEqual(packaging.barcode, "1234")
        packaging_barcode.unlink()
        self.assertFalse(packaging.exists())
        product.barcode = "1234"

    def test_duplicated_barcodes_are_allowed_for_different_companies(self):
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "CB"})

        allowed_products = [
            {"name": "A1", "barcode": "3", "company_id": company_a.id},
            {"name": "A2", "barcode": "3", "company_id": company_b.id},
        ]

        forbidden_products = [
            {"name": "F1", "barcode": "1", "company_id": False},
            {"name": "F2", "barcode": "1", "company_id": company_a.id},
            {"name": "F3", "barcode": "2", "company_id": company_b.id},
            {"name": "F4", "barcode": "3", "company_id": company_a.id},
            {"name": "F5", "barcode": "3", "company_id": company_b.id},
            {"name": "F6", "barcode": "3", "company_id": False},
        ]

        for product in allowed_products:
            self.env["product.product"].create(product)

        for product in forbidden_products:
            with self.assertRaises(ValidationError):
                self.env["product.product"].create(product)

    def test_duplicated_barcodes_in_product_variants(self):
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "CB"})

        variant_1 = self.template.product_variant_ids[0]
        variant_2 = self.template.product_variant_ids[1]

        variant_1.barcode = "barcode_1"
        variant_1.company_id = company_a
        variant_2.barcode = "barcode_2"
        variant_2.company_id = company_a

        with self.assertRaises(ValidationError):
            variant_2.write({"barcode": "barcode_1", "company_id": company_b})

        self.assertEqual(variant_2.barcode, "barcode_2")
        self.assertEqual(variant_2.company_id, company_a)

        variant_2.write({"barcode": "barcode_3", "company_id": company_b})

        self.assertEqual(variant_1.barcode, "barcode_1")
        self.assertEqual(variant_1.company_id, company_b)
        self.assertEqual(variant_2.barcode, "barcode_3")
        self.assertEqual(variant_2.company_id, company_b)
