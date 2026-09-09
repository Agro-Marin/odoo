import ast

from lxml import etree

from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


class TestProductManufacturer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.manufacturer_a = cls.env["res.partner"].create({"name": "Manufacturer A"})
        cls.manufacturer_b = cls.env["res.partner"].create({"name": "Manufacturer B"})
        cls.attr1 = cls.env["product.attribute"].create({"name": "color"})
        cls.attr1_1 = cls.env["product.attribute.value"].create(
            {"name": "red", "attribute_id": cls.attr1.id}
        )
        cls.attr1_2 = cls.env["product.attribute.value"].create(
            {"name": "blue", "attribute_id": cls.attr1.id}
        )
        cls.product1 = cls.env["product.template"].create(
            {
                "name": "Test Product Manufacturer 1",
            }
        )

    def test_01_product_manufacturer(self):
        self.product1.update(
            {
                "manufacturer_id": self.manufacturer_a.id,
                "manufacturer_pname": "Test Product A",
                "manufacturer_pref": "TPA",
                "manufacturer_purl": "https://www.manufacturera.com/test_product_a",
            }
        )

        self.assertEqual(
            self.product1.product_variant_id.manufacturer_id.id,
            self.manufacturer_a.id,
        )
        self.assertEqual(
            self.product1.product_variant_id.manufacturer_pname,
            "Test Product A",
        )
        self.assertEqual(self.product1.product_variant_id.manufacturer_pref, "TPA")
        self.assertEqual(
            self.product1.product_variant_id.manufacturer_purl,
            "https://www.manufacturera.com/test_product_a",
        )

    def test_02_product_manufacturer(self):
        self.product1.update(
            {
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": self.attr1.id,
                            "value_ids": [
                                Command.set([self.attr1_1.id, self.attr1_2.id])
                            ],
                        }
                    ),
                ],
            }
        )
        self.product1.product_variant_ids[0].update(
            {
                "manufacturer_id": self.manufacturer_b.id,
                "manufacturer_pname": "Test Product B",
                "manufacturer_pref": "TPB",
                "manufacturer_purl": "https://www.manufacturerb.com/test_product_b",
            }
        )
        self.product1.product_variant_ids[1].update(
            {
                "manufacturer_id": self.manufacturer_a.id,
                "manufacturer_pname": "Test Product A",
                "manufacturer_pref": "TPA",
                "manufacturer_purl": "https://www.manufacturera.com/test_product_a",
            }
        )
        self.assertEqual(self.product1.manufacturer_id.id, False)
        self.assertEqual(self.product1.manufacturer_pname, False)
        self.assertEqual(self.product1.manufacturer_pref, False)
        self.assertEqual(self.product1.manufacturer_purl, False)
        self.assertEqual(
            self.product1.product_variant_ids[1].manufacturer_id.id,
            self.manufacturer_a.id,
        )
        self.assertEqual(
            self.product1.product_variant_ids[1].manufacturer_pname,
            "Test Product A",
        )
        self.assertEqual(self.product1.product_variant_ids[1].manufacturer_pref, "TPA")
        self.assertEqual(
            self.product1.product_variant_ids[1].manufacturer_purl,
            "https://www.manufacturera.com/test_product_a",
        )
        self.assertEqual(
            self.product1.product_variant_ids[0].manufacturer_id.id,
            self.manufacturer_b.id,
        )
        self.assertEqual(
            self.product1.product_variant_ids[0].manufacturer_pname,
            "Test Product B",
        )
        self.assertEqual(self.product1.product_variant_ids[0].manufacturer_pref, "TPB")
        self.assertEqual(
            self.product1.product_variant_ids[0].manufacturer_purl,
            "https://www.manufacturerb.com/test_product_b",
        )

    def test_03_product_manufacturer_creation(self):
        new_pt = self.env["product.template"].create(
            {
                "name": "New Product Template",
                "manufacturer_id": self.manufacturer_a.id,
                "manufacturer_pname": "Test Product A",
                "manufacturer_pref": "TPA",
                "manufacturer_purl": "https://www.manufacturera.com/test_product_a",
            }
        )

        self.assertEqual(
            new_pt.product_variant_id.manufacturer_id.id,
            new_pt.manufacturer_id.id,
        )
        self.assertEqual(
            new_pt.product_variant_id.manufacturer_pname,
            new_pt.manufacturer_pname,
        )
        self.assertEqual(
            new_pt.product_variant_id.manufacturer_pref,
            new_pt.manufacturer_pref,
        )
        self.assertEqual(
            new_pt.product_variant_id.manufacturer_purl,
            new_pt.manufacturer_purl,
        )

    def test_04_manufacturer_survives_archiving_the_only_variant(self):
        """The template keeps its manufacturer when its one variant is archived.

        `product_variant_ids` hides archived variants, so a compute reading it
        alone sees no variant and clears all four fields.
        """
        self.product1.update(
            {
                "manufacturer_id": self.manufacturer_a.id,
                "manufacturer_pname": "Test Product A",
                "manufacturer_pref": "TPA",
                "manufacturer_purl": "https://www.manufacturera.com/test_product_a",
            }
        )
        variant = self.product1.product_variant_id
        variant.active = False
        self.product1.invalidate_recordset(["product_variant_ids"])
        self.assertFalse(self.product1.product_variant_ids)

        for fname in (
            "manufacturer_id",
            "manufacturer_pname",
            "manufacturer_pref",
            "manufacturer_purl",
        ):
            self.env.add_to_compute(
                self.env["product.template"]._fields[fname], self.product1
            )
        self.env.flush_all()

        self.assertEqual(self.product1.manufacturer_id.id, self.manufacturer_a.id)
        self.assertEqual(self.product1.manufacturer_pname, "Test Product A")
        self.assertEqual(self.product1.manufacturer_pref, "TPA")
        self.assertEqual(
            self.product1.manufacturer_purl,
            "https://www.manufacturera.com/test_product_a",
        )

    def test_05_writing_a_manufacturer_reaches_the_archived_variant(self):
        """The inverse pushes down to the single variant even when archived."""
        variant = self.product1.product_variant_id
        variant.active = False
        self.product1.invalidate_recordset(["product_variant_ids"])
        self.assertFalse(self.product1.product_variant_ids)

        self.product1.update(
            {
                "manufacturer_id": self.manufacturer_b.id,
                "manufacturer_pname": "Test Product B",
                "manufacturer_pref": "TPB",
                "manufacturer_purl": "https://www.manufacturerb.com/test_product_b",
            }
        )

        self.assertEqual(variant.manufacturer_id.id, self.manufacturer_b.id)
        self.assertEqual(variant.manufacturer_pname, "Test Product B")
        self.assertEqual(variant.manufacturer_pref, "TPB")
        self.assertEqual(
            variant.manufacturer_purl,
            "https://www.manufacturerb.com/test_product_b",
        )


@tagged("-at_install", "post_install")
class TestManufacturerInlineCreate(TransactionCase):
    """The `manufacturer_id` views must create a partner their own domain
    accepts, and must not rank it as a vendor. `account` declares
    `supplier_rank` and stamps it from `res_partner_search_mode`, and it
    installs after `product`, so this runs post_install."""

    VIEWS = (
        ("product.view_product_template_form", "product.template"),
        ("product.view_product_product_form_easy_edit", "product.product"),
    )

    def _field_context(self, xmlid, model):
        """The context the client would actually send for an inline create."""
        view = self.env.ref(xmlid)
        arch = etree.fromstring(self.env[model].get_view(view.id, "form")["arch"])
        node = arch.xpath("//field[@name='manufacturer_id']")[0]
        return ast.literal_eval(node.get("context"))

    def test_the_view_context_defaults_the_manufacturer_flag(self):
        # read the field node's own context rather than the whole arch: these
        # are the base product forms now, and post_install they carry vendor
        # fields whose context legitimately names `res_partner_search_mode`.
        for xmlid, model in self.VIEWS:
            context = self._field_context(xmlid, model)
            self.assertTrue(context["default_manufacturer"])
            self.assertNotIn("res_partner_search_mode", context)

    def test_an_inline_created_partner_satisfies_the_field_domain(self):
        for xmlid, model in self.VIEWS:
            context = self._field_context(xmlid, model)
            partner = (
                self.env["res.partner"]
                .with_context(**context)
                .create({"name": f"Inline Manufacturer {model}"})
            )
            self.assertTrue(partner.manufacturer)
            # `supplier_rank` is declared by `account`, which `product` does not
            # depend on, so the rank half of the claim only applies where the
            # field exists.
            if "supplier_rank" in partner._fields:
                self.assertEqual(partner.supplier_rank, 0)
            self.assertTrue(
                self.env["res.partner"].search_count(
                    [("id", "=", partner.id), ("manufacturer", "=", True)]
                )
            )
