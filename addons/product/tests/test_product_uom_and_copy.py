from collections import defaultdict

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDuplicatedRecordsetCopy(TransactionCase):
    """`copy_data` answers a record it has already copied in this operation with
    a ``None`` entry (see `CopyMixin.copy_data`), which `copy()` then drops. Every
    override in this addon used to index into that entry unconditionally.

    A repeated record in the recordset is now refused by the ORM itself (see
    `base.tests.test_copy`), so these check the two things this addon still owns:
    its overrides tolerate a `None` entry whatever produces it, and the normal
    single-record path still renames correctly.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")

    def _assert_copy_data_tolerates_a_none_entry(self, record):
        """Feed the override the shape the recursion guard produces -- a record
        it has already copied -- and check it neither raises nor renames it."""
        seen = defaultdict(set)
        seen[record._name].add(record.id)
        vals_list = record.with_context(__copy_data_seen=seen).copy_data()
        self.assertEqual(vals_list, [None])

        # ... and the ordinary path still renames.
        vals_list = record.copy_data()
        self.assertEqual(len(vals_list), 1)
        self.assertIsInstance(vals_list[0], dict)
        return vals_list[0]

    def test_copy_duplicated_template(self):
        template = self.env["product.template"].create(
            {"name": "Dup Tmpl", "uom_id": self.uom_unit.id}
        )
        vals = self._assert_copy_data_tolerates_a_none_entry(template)
        self.assertEqual(vals["name"], "Dup Tmpl (copy)")

    def test_copy_duplicated_category(self):
        category = self.env["product.category"].create({"name": "Dup Categ"})
        vals = self._assert_copy_data_tolerates_a_none_entry(category)
        self.assertEqual(vals["name"], "Dup Categ (copy)")

    def test_copy_duplicated_tag(self):
        tag = self.env["product.tag"].create({"name": "Dup Tag"})
        vals = self._assert_copy_data_tolerates_a_none_entry(tag)
        self.assertEqual(vals["name"], "Dup Tag (copy)")

    def test_copy_duplicated_pricelist(self):
        pricelist = self.env["product.pricelist"].create(
            {"name": "Dup PL", "currency_id": self.env.company.currency_id.id}
        )
        vals = self._assert_copy_data_tolerates_a_none_entry(pricelist)
        self.assertEqual(vals["name"], "Dup PL (copy)")

    def test_copy_duplicated_document(self):
        template = self.env["product.template"].create(
            {"name": "Doc Holder", "uom_id": self.uom_unit.id}
        )
        document = self.env["product.document"].create(
            {
                "ir_attachment_id": self.env["ir.attachment"]
                .create(
                    {
                        "name": "Dup Doc",
                        "raw": b"x",
                        "res_model": "product.template",
                        "res_id": template.id,
                    }
                )
                .id
            }
        )
        attachments_before = self.env["ir.attachment"].search_count([])
        vals = self._assert_copy_data_tolerates_a_none_entry(document)
        # `copy_data` is what clones the attachment here, so a skipped entry
        # must not leave an orphan behind: exactly one new attachment, for the
        # one entry that will actually be created.
        self.assertEqual(
            self.env["ir.attachment"].search_count([]), attachments_before + 1
        )
        self.assertTrue(vals["ir_attachment_id"])
        self.assertNotEqual(vals["ir_attachment_id"], document.ir_attachment_id.id)

    def test_copy_several_variants_of_one_template(self):
        """`product.product.copy()` used to build one template entry per variant,
        feeding `copy()` a recordset with the same template twice."""
        attribute = self.env["product.attribute"].create({"name": "Dup Size"})
        values = self.env["product.attribute.value"].create(
            [{"name": name, "attribute_id": attribute.id} for name in ("S", "M")]
        )
        template = self.env["product.template"].create(
            {
                "name": "Dup Variants",
                "uom_id": self.uom_unit.id,
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [(6, 0, values.ids)],
                        },
                    )
                ],
            }
        )
        variants = template.product_variant_ids
        self.assertEqual(len(variants), 2)

        copies = variants.copy()

        # One duplicated product (carrying both its variants), not two.
        self.assertEqual(len(copies.product_tmpl_id), 1)
        self.assertNotEqual(copies.product_tmpl_id, template)
        self.assertEqual(copies.product_tmpl_id.name, "Dup Variants (copy)")
        self.assertEqual(len(copies.product_tmpl_id.product_variant_ids), 2)

    def test_copy_template_keeps_price_extra_per_template(self):
        """The extra prices must be re-applied template by template, not by
        position across the flattened attribute lines of the whole batch."""
        attribute = self.env["product.attribute"].create({"name": "Dup Colour"})
        red, blue = self.env["product.attribute.value"].create(
            [{"name": name, "attribute_id": attribute.id} for name in ("Red", "Blue")]
        )
        templates = self.env["product.template"].create(
            [
                {
                    "name": name,
                    "uom_id": self.uom_unit.id,
                    "attribute_line_ids": [
                        (
                            0,
                            0,
                            {
                                "attribute_id": attribute.id,
                                "value_ids": [(6, 0, (red + blue).ids)],
                            },
                        )
                    ],
                }
                for name in ("Batch A", "Batch B")
            ]
        )
        for index, template in enumerate(templates):
            template.attribute_line_ids.product_template_value_ids.filtered(
                lambda ptav: ptav.product_attribute_value_id == red
            ).price_extra = 10.0 * (index + 1)

        copies = templates.copy()

        for template, copy in zip(templates, copies, strict=True):
            source = template.attribute_line_ids.product_template_value_ids.filtered(
                lambda ptav: ptav.product_attribute_value_id == red
            )
            copied = copy.attribute_line_ids.product_template_value_ids.filtered(
                lambda ptav: ptav.product_attribute_value_id == red
            )
            self.assertEqual(copied.price_extra, source.price_extra)


@tagged("post_install", "-at_install")
class TestPriceUomConversion(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")
        cls.uom_kgm = cls.env.ref("uom.product_uom_kgm")

        attribute = cls.env["product.attribute"].create({"name": "Price Colour"})
        cls.red, cls.blue = cls.env["product.attribute.value"].create(
            [{"name": name, "attribute_id": attribute.id} for name in ("Red", "Blue")]
        )
        cls.template = cls.env["product.template"].create(
            {
                "name": "Priced Product",
                "list_price": 100.0,
                "uom_id": cls.uom_unit.id,
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [(6, 0, (cls.red + cls.blue).ids)],
                        },
                    )
                ],
            }
        )
        cls.ptav_red = (
            cls.template.attribute_line_ids.product_template_value_ids.filtered(
                lambda ptav: ptav.product_attribute_value_id == cls.red
            )
        )
        cls.ptav_red.price_extra = 10.0
        cls.variant = cls.template.product_variant_ids.filtered(
            lambda p: cls.ptav_red in p.product_template_attribute_value_ids
        )

    def test_lst_price_converts_the_attribute_extra_too(self):
        """`lst_price` under a UoM context must agree with `_compute_price`."""
        self.assertEqual(self.variant.lst_price, 110.0)
        in_dozen = self.variant.with_context(uom=self.uom_dozen.id).lst_price
        self.assertEqual(
            in_dozen,
            self.variant._compute_price("list_price", uom=self.uom_dozen)[
                self.variant.id
            ],
        )
        # 12 x (100 list + 10 attribute extra), not 12 x 100 + 10.
        self.assertEqual(in_dozen, 1320.0)

    def test_lst_price_round_trips_through_its_inverse(self):
        variant_in_dozen = self.variant.with_context(uom=self.uom_dozen.id)
        variant_in_dozen.lst_price = 2400.0
        self.assertEqual(self.variant.list_price, 190.0)  # 2400/12 - 10
        self.variant.invalidate_recordset()
        self.assertEqual(
            self.variant.with_context(uom=self.uom_dozen.id).lst_price, 2400.0
        )

    def test_lst_price_refuses_an_incompatible_uom(self):
        """The guard `_compute_price` already applies must not be bypassed."""
        with self.assertRaises(UserError):
            self.variant.with_context(uom=self.uom_kgm.id).read(["lst_price"])

    def test_convert_price_from_uom_inverts_convert_price_to_uom(self):
        self.assertEqual(
            self.variant._convert_price_from_uom(
                self.variant._convert_price_to_uom(37.0, self.uom_dozen),
                self.uom_dozen,
            ),
            37.0,
        )
        with self.assertRaises(UserError):
            self.variant._convert_price_from_uom(1.0, self.uom_kgm)

    def test_fixed_pricelist_rule_refuses_an_incompatible_uom(self):
        """A fixed-price rule used to return silent nonsense where a formula
        rule -- the same request by another route -- raised."""
        pricelist = self.env["product.pricelist"].create(
            {"name": "UoM PL", "currency_id": self.env.company.currency_id.id}
        )
        rule = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": pricelist.id,
                "applied_on": "1_product",
                "product_tmpl_id": self.template.id,
                "compute_price": "fixed",
                "fixed_price": 50.0,
            }
        )
        # Compatible unit: still converted as before.
        self.assertEqual(
            pricelist._get_product_price(self.variant, 1.0, uom=self.uom_dozen), 600.0
        )
        with self.assertRaises(UserError):
            pricelist._get_product_price(self.variant, 1.0, uom=self.uom_kgm)

        # ... and the formula branch keeps refusing it too.
        rule.write({"compute_price": "percentage", "percent_price": 10.0})
        with self.assertRaises(UserError):
            pricelist._get_product_price(self.variant, 1.0, uom=self.uom_kgm)

        # A pricelist prices templates as well as variants, and the rule-side
        # conversion calls the guard on whichever model it was handed, so both
        # must expose it.
        rule.write({"compute_price": "fixed", "fixed_price": 50.0})
        self.assertEqual(
            pricelist._get_product_price(self.template, 1.0, uom=self.uom_dozen), 600.0
        )
        with self.assertRaises(UserError):
            pricelist._get_product_price(self.template, 1.0, uom=self.uom_kgm)

    def test_price_uom_guard_is_symmetric_between_template_and_variant(self):
        """The two models carry parallel copies of the price-conversion helpers
        (`_inherits` delegates fields, not methods); they must not drift."""
        for record in (self.template, self.variant):
            self.assertTrue(hasattr(record, "_check_price_uom"))
            self.assertEqual(record._convert_price_to_uom(10.0, self.uom_dozen), 120.0)
            with self.assertRaises(UserError):
                record._convert_price_to_uom(10.0, self.uom_kgm)

    def test_supplierinfo_price_discounted_keeps_the_product_uom_contract(self):
        """`price_discounted` is documented as being expressed in the *product's*
        UoM, and `purchase.order._get_product_catalog_order_line_info` converts it
        back into the vendor's UoM for display. Locking the round trip: it is what
        makes the cross-category value (meaningless on its own) unsafe to "fix"
        without changing that caller too.
        """
        vendor = self.env["res.partner"].create({"name": "UoM Vendor"})
        seller = self.env["product.supplierinfo"].create(
            {
                "partner_id": vendor.id,
                "product_tmpl_id": self.template.id,
                "price": 120.0,
                "product_uom_id": self.uom_dozen.id,
            }
        )
        self.assertEqual(seller.price_discounted, 10.0)
        self.assertEqual(
            self.uom_unit._compute_price(
                seller.price_discounted, seller.product_uom_id
            ),
            120.0,
        )


@tagged("post_install", "-at_install")
class TestPackagingUomCategory(TransactionCase):
    """`uom_ids` only excluded `uom_id` itself, so a product measured in Units
    could be given a "kg" packaging through the normal form -- and order lines
    union `uom_ids` into their allowed units. That is the configuration that let
    a 50.00 fixed-price rule price a sale line at 50000.00.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")
        cls.uom_kgm = cls.env.ref("uom.product_uom_kgm")
        # `uom.product_uom_dozen` ships archived (it only becomes selectable once
        # the UoM feature is enabled), and a many2many read filters archived
        # records out -- so without this the packaging would silently read back
        # empty and the assertions below would test nothing.
        cls.uom_dozen.action_unarchive()

    def test_packaging_in_the_same_category_is_allowed(self):
        template = self.env["product.template"].create(
            {
                "name": "Boxed Product",
                "uom_id": self.uom_unit.id,
                "uom_ids": [(6, 0, self.uom_dozen.ids)],
            }
        )
        self.assertEqual(template.uom_ids, self.uom_dozen)

    def test_packaging_from_another_category_is_refused_on_create(self):
        with self.assertRaises(ValidationError):
            self.env["product.template"].create(
                {
                    "name": "Impossible Packaging",
                    "uom_id": self.uom_unit.id,
                    "uom_ids": [(6, 0, self.uom_kgm.ids)],
                }
            )

    def test_packaging_from_another_category_is_refused_on_write(self):
        template = self.env["product.template"].create(
            {"name": "Later Packaging", "uom_id": self.uom_unit.id}
        )
        with self.assertRaises(ValidationError):
            template.uom_ids = self.uom_kgm

    def test_changing_the_unit_revalidates_existing_packagings(self):
        """The constraint watches `uom_id` too: moving the product to another
        category must not leave its packagings stranded."""
        template = self.env["product.template"].create(
            {
                "name": "Rebased Product",
                "uom_id": self.uom_unit.id,
                "uom_ids": [(6, 0, self.uom_dozen.ids)],
            }
        )
        with self.assertRaises(ValidationError):
            template.uom_id = self.uom_kgm


@tagged("post_install", "-at_install")
class TestTemplateUomChange(TransactionCase):
    def test_uom_change_covers_archived_variants(self):
        """Changing the unit restamps it on every document referencing the
        product, so archived variants must be handed to `_update_uom` too."""
        uom_unit = self.env.ref("uom.product_uom_unit")
        uom_dozen = self.env.ref("uom.product_uom_dozen")
        attribute = self.env["product.attribute"].create({"name": "Archived Size"})
        values = self.env["product.attribute.value"].create(
            [{"name": name, "attribute_id": attribute.id} for name in ("S", "M")]
        )
        template = self.env["product.template"].create(
            {
                "name": "Archived Variant Product",
                "uom_id": uom_unit.id,
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [(6, 0, values.ids)],
                        },
                    )
                ],
            }
        )
        archived = template.product_variant_ids[0]
        archived.action_archive()
        self.assertFalse(archived.active)

        seen = []
        product_model = type(self.env["product.product"])
        original = product_model._update_uom

        def spy(records, to_uom_id):
            seen.extend(records.ids)
            return original(records, to_uom_id)

        self.patch(product_model, "_update_uom", spy)
        template.write({"uom_id": uom_dozen.id})

        all_variants = template.with_context(active_test=False).product_variant_ids
        self.assertEqual(sorted(seen), sorted(all_variants.ids))
        self.assertIn(archived.id, seen)
