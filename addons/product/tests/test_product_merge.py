from ast import literal_eval

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.product.tests.common import ProductVariantsCommon


@tagged("post_install", "-at_install")
class TestProductMerge(ProductVariantsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wizard = cls.env["product.merge.wizard"].create({})
        cls.vendor = cls.env["res.partner"].create({"name": "Merge Test Vendor"})

    @classmethod
    def _create_template(cls, name, **values):
        return cls.env["product.template"].create(
            {
                "name": name,
                "type": "consu",
                "uom_id": cls.uom_unit.id,
                "categ_id": cls.product_category.id,
                **values,
            }
        )

    @classmethod
    def _create_color_template(cls, name, colors, **values):
        return cls._create_template(
            name,
            attribute_line_ids=[
                Command.create(
                    {
                        "attribute_id": cls.color_attribute.id,
                        "value_ids": [Command.set(colors.ids)],
                    }
                )
            ],
            **values,
        )

    def _get_variant(self, template, color):
        return template.product_variant_ids.filtered(
            lambda variant: (
                color
                in variant.product_template_attribute_value_ids.product_attribute_value_id
            )
        )

    def test_merge_repoints_documents_to_the_destination(self):
        destination = self._create_template("Merge Target")
        source = self._create_template("Merge Source")

        pricelist_item = self.env["product.pricelist.item"].create(
            {
                "pricelist_id": self.pricelist.id,
                "applied_on": "1_product",
                "product_tmpl_id": source.id,
                "fixed_price": 5.0,
            }
        )
        seller = self.env["product.supplierinfo"].create(
            {
                "partner_id": self.vendor.id,
                "product_tmpl_id": source.id,
                "price": 3.0,
            }
        )
        template_attachment = self.env["ir.attachment"].create(
            {
                "name": "Source template datasheet",
                "res_model": "product.template",
                "res_id": source.id,
            }
        )
        variant_attachment = self.env["ir.attachment"].create(
            {
                "name": "Source variant datasheet",
                "res_model": "product.product",
                "res_id": source.product_variant_id.id,
            }
        )
        source_variant = source.product_variant_id

        self.wizard._merge([source.id, destination.id], destination)

        self.assertFalse(source.exists(), "The source template is deleted")
        self.assertFalse(source_variant.exists(), "Its variant goes with it")
        self.assertTrue(destination.exists())
        self.assertEqual(pricelist_item.product_tmpl_id, destination)
        self.assertEqual(seller.product_tmpl_id, destination)
        self.assertEqual(template_attachment.res_id, destination.id)
        self.assertEqual(variant_attachment.res_id, destination.product_variant_id.id)

    def test_merge_fills_only_the_gaps_of_the_destination(self):
        destination = self._create_template(
            "Kept Values", description_purchase="Written by the destination"
        )
        source = self._create_template(
            "Dropped Values",
            description_purchase="Written by the source",
            default_code="SOURCE-REF",
            barcode="MERGE-SRC-BARCODE",
        )

        self.wizard._merge([source.id, destination.id], destination)

        self.assertEqual(
            destination.description_purchase,
            "Written by the destination",
            "A field the destination answers for is never overwritten",
        )
        self.assertEqual(
            destination.default_code,
            "SOURCE-REF",
            "A field it leaves empty is taken from the source",
        )
        self.assertEqual(
            destination.barcode,
            "MERGE-SRC-BARCODE",
            "Including the barcode, which can only be written once the source "
            "holding it is gone",
        )

    def test_merge_absorbs_several_sources_at_once(self):
        destination = self._create_template("Three Way Target")
        first_source = self._create_template(
            "Three Way Source A", barcode="MERGE-THREE-WAY"
        )
        second_source = self._create_template(
            "Three Way Source B", default_code="THREE-WAY-REF"
        )

        self.wizard._merge(
            [first_source.id, second_source.id, destination.id], destination
        )

        self.assertFalse((first_source + second_source).exists())
        self.assertEqual(
            destination.barcode,
            "MERGE-THREE-WAY",
            "What the first source contributes survives the second one",
        )
        self.assertEqual(destination.default_code, "THREE-WAY-REF")

    def test_merge_pairs_variants_on_their_attribute_values(self):
        colors = self.color_attribute_red + self.color_attribute_blue
        destination = self._create_color_template("Shirt", colors)
        source = self._create_color_template("Shirt Duplicate", colors)

        source_red = self._get_variant(source, self.color_attribute_red)
        destination_red = self._get_variant(destination, self.color_attribute_red)
        destination_blue = self._get_variant(destination, self.color_attribute_blue)
        red_attachment = self.env["ir.attachment"].create(
            {
                "name": "Red datasheet",
                "res_model": "product.product",
                "res_id": source_red.id,
            }
        )

        self.wizard._merge([source.id, destination.id], destination)

        self.assertEqual(
            red_attachment.res_id,
            destination_red.id,
            "The document follows the combination, not the position",
        )
        self.assertEqual(
            destination.product_variant_ids,
            destination_red + destination_blue,
            "The destination keeps exactly the variants it had: its attribute "
            "lines are never re-pointed, so nothing is regenerated",
        )
        self.assertEqual(len(destination.attribute_line_ids), 1)

    def test_merge_pairs_by_value_not_by_position(self):
        destination = self._create_color_template(
            "Mug", self.color_attribute_red + self.color_attribute_blue
        )
        source = self._create_color_template("Mug Duplicate", self.color_attribute_blue)

        source_blue = source.product_variant_id
        destination_red = self._get_variant(destination, self.color_attribute_red)
        destination_blue = self._get_variant(destination, self.color_attribute_blue)
        attachment = self.env["ir.attachment"].create(
            {
                "name": "Blue datasheet",
                "res_model": "product.product",
                "res_id": source_blue.id,
            }
        )

        self.wizard._merge([source.id, destination.id], destination)

        self.assertEqual(attachment.res_id, destination_blue.id)
        self.assertNotEqual(attachment.res_id, destination_red.id)

    def test_merge_refuses_an_unmatched_combination(self):
        destination = self._create_color_template(
            "Cap", self.color_attribute_red + self.color_attribute_blue
        )
        source = self._create_color_template(
            "Cap Duplicate", self.color_attribute_red + self.color_attribute_green
        )

        with self.assertRaises(UserError):
            self.wizard._merge([source.id, destination.id], destination)

        self.assertTrue(source.exists(), "Nothing is merged when a variant has no pair")
        self.assertTrue(destination.exists())

    def test_merge_refuses_products_measured_differently(self):
        destination = self._create_template("Rope by unit")
        source = self._create_template("Rope by dozen", uom_id=self.uom_dozen.id)

        with self.assertRaises(UserError):
            self.wizard._merge([source.id, destination.id], destination)

        self.assertTrue(source.exists())

    def test_merge_refuses_products_of_different_types(self):
        destination = self._create_template("Delivered good")
        source = self._create_template("Delivered service", type="service")

        with self.assertRaises(UserError):
            self.wizard._merge([source.id, destination.id], destination)

        self.assertTrue(source.exists())

    def test_merge_refuses_more_than_three_products(self):
        templates = self.env["product.template"].concat(
            *[self._create_template(f"Too many {index}") for index in range(4)]
        )

        with self.assertRaises(UserError):
            self.wizard._merge(templates.ids)

        self.assertEqual(len(templates.exists()), 4)

    def test_merge_logs_the_operation_on_the_destination(self):
        destination = self._create_template("Logged Target")
        source = self._create_template("Logged Source")

        self.wizard._merge([source.id, destination.id], destination)

        self.assertTrue(
            destination.message_ids.filtered(
                lambda message: "Logged Source" in (message.body or "")
            ),
            "The destination records which products it absorbed",
        )

    def test_selecting_variants_merges_their_templates(self):
        destination = self._create_color_template(
            "Selected", self.color_attribute_red + self.color_attribute_blue
        )
        source = self._create_color_template(
            "Selected Duplicate", self.color_attribute_red + self.color_attribute_blue
        )
        destination.write({"create_date": "2020-01-01 00:00:00"})
        source.write({"create_date": "2024-01-01 00:00:00"})

        wizard = (
            self.env["product.merge.wizard"]
            .with_context(
                active_model="product.product",
                active_ids=(
                    source.product_variant_ids + destination.product_variant_ids
                ).ids,
            )
            .create({})
        )

        self.assertEqual(
            wizard.product_tmpl_ids,
            source + destination,
            "A variant selection is resolved to the templates behind it",
        )
        self.assertEqual(
            wizard.dst_product_tmpl_id,
            destination,
            "The oldest active product is proposed as the destination",
        )

    def test_action_merge_needs_two_products(self):
        wizard = self.env["product.merge.wizard"].create(
            {
                "state": "selection",
                "product_tmpl_ids": [Command.set(self._create_template("Alone").ids)],
            }
        )

        with self.assertRaises(UserError):
            wizard.action_merge()

    def test_manual_process_groups_duplicates(self):
        destination = self._create_template("Deduplicated", default_code="DEDUP-REF")
        source = self._create_template("deduplicated", default_code="dedup-ref")
        self._create_template("Not deduplicated", default_code="DEDUP-OTHER")

        wizard = self.env["product.merge.wizard"].create(
            {"group_by_name": True, "group_by_default_code": True}
        )
        wizard.action_start_manual_process()

        self.assertEqual(
            [line.aggr_ids for line in wizard.line_ids],
            [str(sorted((destination + source).ids))],
            "Name and internal reference are compared case-insensitively, and "
            "the product nobody duplicates is left alone",
        )

    def test_automatic_process_skips_a_group_it_refuses(self):
        refused = [
            self._create_template("Refused", default_code="REFUSED-REF")
            for _index in range(4)
        ]

        wizard = self.env["product.merge.wizard"].create(
            {"group_by_name": True, "group_by_default_code": True}
        )
        wizard.action_start_automatic_process()

        self.assertEqual(
            len(self.env["product.template"].concat(*refused).exists()),
            4,
            "A group of four is over the safety cap, so none of it is merged",
        )
        self.assertTrue(
            wizard.line_ids,
            "And the group stays on the wizard for the user to settle by hand",
        )
        self.assertEqual(wizard.state, "selection")

    def test_automatic_process_merges_every_group(self):
        destination = self._create_template("Swept", default_code="SWEEP-REF")
        source = self._create_template("Swept", default_code="SWEEP-REF")

        wizard = self.env["product.merge.wizard"].create(
            {"group_by_name": True, "group_by_default_code": True}
        )
        wizard.action_start_automatic_process()

        self.assertEqual(wizard.state, "finished")
        self.assertFalse(wizard.line_ids)
        self.assertEqual(
            len((destination + source).exists()),
            1,
            "The group found by the search is merged down to one product",
        )

    def test_merge_never_narrows_the_company_of_the_destination(self):
        shared = self._create_template("Shared Target")
        company = self.env["res.company"].browse(self.env.company.id)
        scoped = self._create_template("Scoped Source", company_id=company.id)

        self.wizard._merge([scoped.id, shared.id], shared)

        self.assertFalse(
            shared.company_id,
            "The destination keeps its own company scope, not the source's",
        )

    def test_merge_refuses_to_widen_a_scoped_destination(self):
        company = self.env["res.company"].browse(self.env.company.id)
        scoped = self._create_template("Scoped Target", company_id=company.id)
        shared = self._create_template("Shared Source")

        with self.assertRaises(UserError):
            self.wizard._merge([shared.id, scoped.id], scoped)

        self.assertTrue(shared.exists())

    def test_duplicate_search_groups_on_the_variant_barcode(self):
        other_company = self.env["res.company"].create({"name": "Merge Test Co"})
        companies = self.env.company + other_company

        first = self._create_template("Scanned One", company_id=self.env.company.id)
        second = self._create_template("Scanned Two", company_id=other_company.id)
        first.product_variant_id.barcode = "MERGE-SCAN-1"
        second.product_variant_id.with_company(other_company).barcode = "MERGE-SCAN-1"

        wizard = (
            self.env["product.merge.wizard"]
            .with_context(allowed_company_ids=companies.ids)
            .create({"group_by_barcode": True})
        )
        wizard.action_start_manual_process()

        self.assertIn(
            str(sorted((first + second).ids)),
            [line.aggr_ids for line in wizard.line_ids],
            "Both products are proposed as one group",
        )

    def test_duplicate_search_ignores_products_without_the_criterion(self):
        uncategorised = [
            self._create_template(f"No Category {index}", categ_id=False)
            for index in range(2)
        ]

        wizard = self.env["product.merge.wizard"].create({"group_by_categ_id": True})
        wizard.action_start_manual_process()

        grouped = {
            template_id
            for line in wizard.line_ids
            for template_id in literal_eval(line.aggr_ids)
        }
        self.assertFalse(
            grouped & set(self.env["product.template"].concat(*uncategorised).ids)
        )

    def test_skipping_a_group_leaves_it_alone_and_moves_on(self):
        first = self._create_template("Skipped", default_code="SKIP-REF")
        second = self._create_template("Skipped", default_code="SKIP-REF")

        wizard = self.env["product.merge.wizard"].create(
            {"group_by_name": True, "group_by_default_code": True}
        )
        wizard.action_start_manual_process()
        self.assertEqual(wizard.product_tmpl_ids, first + second)

        wizard.action_skip()

        self.assertEqual(wizard.state, "finished")
        self.assertFalse(wizard.line_ids)
        self.assertEqual(len((first + second).exists()), 2, "Nothing was merged")

    def test_a_product_manager_can_merge_without_being_a_superuser(self):
        manager = self.env["res.users"].create(
            {
                "name": "Merge Manager",
                "login": "merge_manager",
                "group_ids": [
                    Command.link(self.env.ref("base.group_user").id),
                    Command.link(self.env.ref("product.group_product_manager").id),
                ],
            }
        )
        destination = self._create_template("Managed Target")
        source = self._create_template("Managed Source", barcode="MERGE-MANAGED")

        wizard = (
            self.env["product.merge.wizard"]
            .with_user(manager)
            .with_context(
                active_model="product.template",
                active_ids=(source + destination).ids,
            )
            .create({})
        )
        wizard.dst_product_tmpl_id = destination
        wizard.action_merge()

        self.assertFalse(source.exists())
        self.assertEqual(destination.barcode, "MERGE-MANAGED")
