from collections import Counter
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import CommonPosTest


@tagged("post_install", "-at_install")
class TestPosProductTemplate(CommonPosTest):
    def setUp(self):
        super().setUp()
        self.config = self.pos_config_usd
        self.config.open_ui()
        self.session = self.config.current_session_id

    def test_pos_sequence_is_unique_across_a_batch_create(self):
        templates = self.env["product.template"].create(
            [{"name": f"Batch product {index}"} for index in range(3)]
        )
        sequences = templates.mapped("pos_sequence")
        self.assertEqual(
            len(set(sequences)),
            3,
            "products created in one call must not share a POS sequence",
        )
        self.assertEqual(sorted(sequences), sequences[:1] + sorted(sequences[1:]))

    def test_pos_sequence_continues_past_records_of_the_same_transaction(self):
        first = self.env["product.template"].create({"name": "Sequence first"})
        second = self.env["product.template"].create({"name": "Sequence second"})
        self.assertGreater(second.pos_sequence, first.pos_sequence)

    def test_pos_sequence_keeps_an_explicit_value(self):
        template = self.env["product.template"].create(
            {"name": "Explicit sequence", "pos_sequence": 4242}
        )
        self.assertEqual(template.pos_sequence, 4242)

    def test_pos_sequence_treats_an_explicit_zero_as_unset(self):
        self.assertNotIn(
            "pos_sequence", self.env["product.template"].default_get(["pos_sequence"])
        )
        template = self.env["product.template"].create(
            {"name": "Zero sequence", "pos_sequence": 0}
        )
        self.assertTrue(template.pos_sequence)

    def test_a_copied_product_gets_its_own_pos_sequence(self):
        source = self.env["product.template"].create({"name": "Sequence source"})
        self.assertNotEqual(source.copy().pos_sequence, source.pos_sequence)

    def test_empty_public_description_is_normalised_on_create(self):
        template = self.env["product.template"].create(
            {"name": "Blank description", "public_description": "<p><br></p>"}
        )
        self.assertEqual(template.public_description, "")

    def test_empty_public_description_is_normalised_on_write(self):
        template = self.env["product.template"].create({"name": "Blank description 2"})
        template.write({"public_description": "<p><br></p>"})
        self.assertEqual(template.public_description, "")

    def test_a_real_public_description_survives(self):
        template = self.env["product.template"].create(
            {"name": "Real description", "public_description": "<p>Tasty</p>"}
        )
        self.assertIn("Tasty", template.public_description)

    def _price_the_other_currency_at(self, rate):
        currency = self.env.ref("base.EUR")
        currency.rate_ids.unlink()
        self.env["res.currency.rate"].create(
            {
                "name": fields.Date.today(),
                "rate": rate,
                "currency_id": currency.id,
                "company_id": self.company.id,
            }
        )
        self.env.invalidate_all()

    def _search_read(self, **context):
        data = {"pos.config": [{"_pos_special_products_ids": []}]}
        return (
            self.env["product.template"]
            .with_context(**context)
            ._load_pos_data_search_read(data, self.config)
        )

    def test_the_loaded_payload_carries_each_template_once(self):
        rows = self._search_read()
        duplicated = [
            template_id
            for template_id, count in Counter(row["id"] for row in rows).items()
            if count > 1
        ]
        self.assertFalse(duplicated, "a template must not be sent to the UI twice")

    def test_the_tip_product_is_loaded(self):
        tip = self.env.ref("point_of_sale.product_product_tip")
        self.config.tip_product_id = tip
        rows = self._search_read()
        self.assertIn(tip.product_tmpl_id.id, [row["id"] for row in rows])

    def test_a_changed_product_survives_the_load_limit(self):
        favourites = self.env["product.template"].create(
            [
                {
                    "name": f"Favourite {index}",
                    "available_in_pos": True,
                    "is_favorite": True,
                }
                for index in range(3)
            ]
        )
        changed = self.env["product.template"].create(
            {"name": "Quietly repriced", "available_in_pos": True}
        )
        self.env.flush_all()
        long_ago = fields.Datetime.now() - timedelta(days=30)
        self.env.cr.execute(
            "UPDATE product_template SET write_date = %s WHERE id != %s",
            (long_ago, changed.id),
        )
        self.env.invalidate_all()
        self.env["ir.config_parameter"].sudo().set_param(
            "point_of_sale.limited_product_count", "3"
        )
        self.env.registry.clear_cache()

        rows = self._search_read(
            pos_last_server_date=fields.Datetime.to_string(
                fields.Datetime.now() - timedelta(days=1)
            ),
            pos_limited_loading=True,
        )
        self.assertIn(
            changed.id,
            [row["id"] for row in rows],
            "an incremental load must rank the products that changed, not the "
            "first page of the unfiltered ordering",
        )
        self.assertFalse(
            set(favourites.ids) & {row["id"] for row in rows},
            "products older than the cut-off have nothing to send",
        )

    def test_the_loaded_payload_reports_the_image_as_a_flag(self):
        rows = self._search_read()
        self.assertTrue(all(isinstance(row["image_128"], bool) for row in rows))

    def test_the_loaded_payload_carries_archived_combinations(self):
        rows = self._search_read()
        self.assertTrue(all("_archived_combinations" in row for row in rows))

    def _uom_barcode_fixture(self):
        variant = self.ten_dollars_no_tax.product_variant_id
        return self.env["product.uom"].create(
            {
                "product_id": variant.id,
                "uom_id": variant.uom_id.id,
                "barcode": "PACKAGING-ONLY-1",
            }
        )

    def _barcode_domain(self, barcode, operator="="):
        value = barcode if operator == "=" else [barcode]
        return [
            "|",
            ("product_variant_ids.barcode", operator, value),
            ("barcode", operator, value),
            ("available_in_pos", "=", True),
            ("sale_ok", "=", True),
        ]

    def test_a_scanned_packaging_barcode_is_found_with_the_equal_operator(self):
        packaging = self._uom_barcode_fixture()
        data = self.env["product.template"].load_product_from_pos(
            self.config.id, self._barcode_domain(packaging.barcode)
        )
        self.assertEqual(
            [row["id"] for row in data["product.uom"]],
            packaging.ids,
            "a barcode given as a scalar must not be exploded into characters",
        )

    def test_a_scanned_packaging_barcode_is_found_with_the_in_operator(self):
        packaging = self._uom_barcode_fixture()
        data = self.env["product.template"].load_product_from_pos(
            self.config.id, self._barcode_domain(packaging.barcode, "in")
        )
        self.assertEqual([row["id"] for row in data["product.uom"]], packaging.ids)

    def test_a_negated_barcode_condition_does_not_load_packagings(self):
        packaging = self._uom_barcode_fixture()
        data = self.env["product.template"].load_product_from_pos(
            self.config.id,
            [
                ("barcode", "!=", packaging.barcode),
                ("id", "=", self.twenty_dollars_no_tax.id),
            ],
        )
        self.assertNotIn(
            packaging.id,
            [row["id"] for row in data["product.uom"]],
            "only a positive barcode condition names a packaging to load",
        )

    def test_a_search_by_barcode_substring_does_not_drag_in_packagings(self):
        packaging = self._uom_barcode_fixture()
        data = self.env["product.template"].load_product_from_pos(
            self.config.id,
            [
                "|",
                ("barcode", "ilike", "PACKAGING"),
                ("product_variant_ids.barcode", "ilike", "PACKAGING"),
                ("available_in_pos", "=", True),
            ],
        )
        self.assertNotIn(packaging.id, [row["id"] for row in data["product.uom"]])

    def test_two_scanned_barcodes_are_both_found(self):
        first = self._uom_barcode_fixture()
        second = self.env["product.uom"].create(
            {
                "product_id": self.twenty_dollars_no_tax.product_variant_id.id,
                "uom_id": self.twenty_dollars_no_tax.uom_id.id,
                "barcode": "PACKAGING-ONLY-2",
            }
        )
        data = self.env["product.template"].load_product_from_pos(
            self.config.id,
            [
                "|",
                ("barcode", "=", first.barcode),
                ("product_variant_ids.barcode", "in", [second.barcode]),
                ("sale_ok", "=", True),
            ],
        )
        self.assertEqual(
            sorted(row["id"] for row in data["product.uom"]),
            sorted((first + second).ids),
            "a scalar and a list condition must each keep their own operator",
        )

    def test_loading_a_product_without_an_open_session_returns_a_payload(self):
        self.session.action_pos_session_closing_control()
        self.config.invalidate_recordset(["current_session_id"])
        data = self.env["product.template"].load_product_from_pos(
            self.config.id, [("id", "=", self.ten_dollars_no_tax.id)]
        )
        self.assertEqual(
            [row["id"] for row in data["product.template"]],
            self.ten_dollars_no_tax.ids,
        )
        self.assertEqual(data["product.pricelist.item"], [])

    def test_a_variant_created_from_the_pos_is_read_like_every_other(self):
        attribute = self.env["product.attribute"].create(
            {
                "name": "Dynamic size",
                "create_variant": "dynamic",
                "value_ids": [
                    Command.create({"name": "S"}),
                    Command.create({"name": "L"}),
                ],
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "Dynamic product",
                "available_in_pos": True,
                "list_price": 100.0,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        value = template.attribute_line_ids.product_template_value_ids[0]
        config = self.pos_config_eur
        self._price_the_other_currency_at(2.0)
        created = template.create_product_variant_from_pos([value.id], config.id)
        variant = self.env["product.product"].browse(
            created["product.product"][0]["id"]
        )
        expected = self.env["product.product"]._load_pos_data_read(variant, config)
        self.assertEqual(created["product.product"], expected)

    def test_a_template_is_loaded_in_the_config_currency(self):
        self._price_the_other_currency_at(2.0)
        config = self.pos_config_eur
        rows = self.env["product.template"]._load_pos_data_read(
            self.ten_dollars_no_tax, config
        )
        self.assertEqual(rows[0]["list_price"], 20.0)

    def test_a_foreign_company_product_is_not_converted_twice(self):
        self._price_the_other_currency_at(2.0)
        other = self.env["res.company"].create(
            {"name": "POS probe EUR co", "currency_id": self.env.ref("base.EUR").id}
        )
        self.env.user.company_ids += other
        template = self.env["product.template"].create(
            {
                "name": "Priced in EUR already",
                "company_id": other.id,
                "list_price": 100.0,
                "available_in_pos": True,
            }
        )
        config = self.pos_config_eur
        self.assertEqual(config.currency_id, self.env.ref("base.EUR"))
        both = {"allowed_company_ids": [self.company.id, other.id]}
        template_row = (
            self.env["product.template"]
            .with_context(**both)
            ._load_pos_data_read(template, config)
        )
        variant_row = (
            self.env["product.product"]
            .with_context(**both)
            ._load_pos_data_read(template.product_variant_id, config)
        )
        self.assertEqual(template_row[0]["list_price"], 100.0)
        self.assertEqual(
            template_row[0]["list_price"],
            variant_row[0]["lst_price"],
            "the template and variant payloads must price the same product alike",
        )

    def test_the_cost_is_the_config_company_cost_not_the_reader_company_cost(self):
        other = self.env["res.company"].create({"name": "POS probe other co"})
        self.env.user.company_ids += other
        variant = self.ten_dollars_no_tax.product_variant_id
        variant.with_company(self.company).standard_price = 11.0
        variant.with_company(other).standard_price = 77.0
        self.env.flush_all()
        config = self.config
        self.assertEqual(config.company_id, self.company)
        model = self.env["product.template"]
        from_home = model._load_pos_data_read(
            self.ten_dollars_no_tax.with_company(self.company), config
        )
        from_other = model._load_pos_data_read(
            self.ten_dollars_no_tax.with_company(other), config
        )
        self.assertEqual(from_home[0]["standard_price"], 11.0)
        self.assertEqual(
            from_other[0]["standard_price"],
            from_home[0]["standard_price"],
            "standard_price is company-dependent; the payload must follow the "
            "config's company, not whoever asked for it",
        )

    def test_the_product_info_lists_each_vendor_once(self):
        template = self.ten_dollars_no_tax
        template.seller_ids = [Command.clear()]
        self.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": self.partner_mobt.id,
                    "product_tmpl_id": template.id,
                    "sequence": 1,
                    "price": 10,
                },
                {
                    "partner_id": self.partner_moda.id,
                    "product_tmpl_id": template.id,
                    "sequence": 2,
                    "price": 20,
                },
                {
                    "partner_id": self.partner_mobt.id,
                    "product_tmpl_id": template.id,
                    "sequence": 3,
                    "price": 30,
                },
            ]
        )
        info = template.get_product_info_pos(10.0, 1, self.config.id)
        vendor_names = [supplier["name"] for supplier in info["suppliers"]]
        self.assertEqual(
            sorted(vendor_names),
            sorted(set(vendor_names)),
            "a vendor with several supplier lines must appear once",
        )
        self.assertEqual(
            vendor_names,
            [self.partner_mobt.name, self.partner_moda.name],
            "vendors keep the order of seller_ids, not of their partner ids",
        )

    def test_the_product_info_keeps_the_cheapest_line_per_vendor_by_sequence(self):
        template = self.twenty_dollars_no_tax
        template.seller_ids = [Command.clear()]
        self.env["product.supplierinfo"].create(
            [
                {
                    "partner_id": self.partner_mobt.id,
                    "product_tmpl_id": template.id,
                    "sequence": 5,
                    "price": 30,
                },
                {
                    "partner_id": self.partner_mobt.id,
                    "product_tmpl_id": template.id,
                    "sequence": 1,
                    "price": 10,
                },
            ]
        )
        info = template.get_product_info_pos(20.0, 1, self.config.id)
        self.assertEqual([s["price"] for s in info["suppliers"]], [10])

    def test_the_product_info_skips_a_vendor_line_outside_its_window(self):
        template = self.ten_dollars_with_5_incl
        template.seller_ids = [Command.clear()]
        yesterday = fields.Date.today() - timedelta(days=1)
        self.env["product.supplierinfo"].create(
            {
                "partner_id": self.partner_mobt.id,
                "product_tmpl_id": template.id,
                "price": 10,
                "date_end": yesterday,
            }
        )
        info = template.get_product_info_pos(10.0, 1, self.config.id)
        self.assertEqual(info["suppliers"], [])

    def test_the_product_info_prices_zero_quantity_without_dividing_by_it(self):
        info = self.ten_dollars_no_tax.get_product_info_pos(10.0, 0, self.config.id)
        self.assertEqual(info["all_prices"]["price_without_tax"], 0)
        self.assertEqual(info["all_prices"]["price_with_tax"], 0)

    def test_the_product_info_puts_the_pos_warehouse_first(self):
        info = self.ten_dollars_no_tax.get_product_info_pos(10.0, 1, self.config.id)
        warehouse_id = self.config.picking_type_id.warehouse_id.id
        if warehouse_id and info["warehouses"]:
            self.assertEqual(info["warehouses"][0]["id"], warehouse_id)

    def test_clearing_sale_ok_by_write_also_clears_available_in_pos(self):
        template = self.env["product.template"].create(
            {"name": "Withdrawn from sale", "available_in_pos": True}
        )
        template.write({"sale_ok": False})
        self.assertFalse(template.available_in_pos)

    def test_creating_a_product_that_is_not_for_sale_leaves_it_out_of_the_pos(self):
        template = self.env["product.template"].create(
            {"name": "Never for sale", "available_in_pos": True, "sale_ok": False}
        )
        self.assertFalse(template.available_in_pos)

    def test_a_product_cannot_be_its_own_optional_product(self):
        template = self.env["product.template"].create({"name": "Self optional"})
        with self.assertRaises(ValidationError):
            template.pos_optional_product_ids = template

    def test_archiving_by_write_is_refused_while_a_session_is_open(self):
        with self.assertRaises(UserError):
            self.ten_dollars_no_tax.write({"active": False})

    def test_archiving_by_action_is_refused_while_a_session_is_open(self):
        with self.assertRaises(UserError):
            self.ten_dollars_no_tax.action_archive()

    def test_a_special_product_cannot_be_archived_by_write(self):
        self.session.action_pos_session_closing_control()
        special = self.env.ref("point_of_sale.product_product_tip").product_tmpl_id
        with self.assertRaises(UserError):
            special.write({"active": False})

    def test_a_configs_custom_tip_product_cannot_be_archived(self):
        tip = self.env["product.template"].create(
            {"name": "House tip", "available_in_pos": True, "type": "service"}
        )
        self.config.tip_product_id = tip.product_variant_id
        self.session.action_pos_session_closing_control()
        with self.assertRaises(UserError):
            tip.write({"active": False})

    def test_the_global_tip_stays_protected_when_no_config_sets_one(self):
        self.session.action_pos_session_closing_control()
        self.env["pos.config"].sudo().search([]).write({"tip_product_id": False})
        tip = self.env.ref("point_of_sale.product_product_tip").product_tmpl_id
        with self.assertRaises(UserError):
            tip.write({"active": False})

    def test_deleting_a_special_product_names_the_product(self):
        self.session.action_pos_session_closing_control()
        special = self.env.ref("point_of_sale.product_product_tip").product_tmpl_id
        with self.assertRaises(UserError) as caught:
            special.unlink()
        self.assertIn(special.display_name, str(caught.exception))

    def _a_two_variant_product(self):
        attribute = self.env["product.attribute"].create(
            {
                "name": "Archive probe size",
                "create_variant": "always",
                "value_ids": [
                    Command.create({"name": "S"}),
                    Command.create({"name": "L"}),
                ],
            }
        )
        return self.env["product.template"].create(
            {
                "name": "Two combinations",
                "available_in_pos": True,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )

    def test_archiving_one_variant_is_allowed_while_a_session_is_open(self):
        template = self._a_two_variant_product()
        variant = template.product_variant_ids[0]
        variant.action_archive()
        self.assertFalse(variant.active)
        self.assertTrue(template.active)

    def test_archiving_the_last_variant_is_refused_while_a_session_is_open(self):
        template = self._a_two_variant_product()
        template.product_variant_ids[0].action_archive()
        with self.assertRaises(UserError):
            template.product_variant_ids[0].action_archive()
        self.assertTrue(template.active)

    def test_archiving_a_special_products_variant_is_refused(self):
        self.session.action_pos_session_closing_control()
        special = self.env.ref("point_of_sale.product_product_tip")
        with self.assertRaises(UserError):
            special.write({"active": False})

    def test_archiving_a_product_outside_the_pos_is_allowed(self):
        template = self.env["product.template"].create({"name": "Not in the shop"})
        template.action_archive()
        self.assertFalse(template.active)
