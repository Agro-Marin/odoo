import datetime

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.modules.module import get_module_path, load_script
from odoo.tests import TransactionCase, tagged


class CatalogAuditCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.supplier = cls.env.ref("stock.stock_location_suppliers")
        cls.customer = cls.env.ref("stock.stock_location_customers")
        cls.Location = cls.env["stock.location"]
        cls.Product = cls.env["product.product"]
        cls.Lot = cls.env["stock.lot"]

    def _done_move(self, product, quantity, source, dest, line_vals=None):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": quantity,
                "location_id": source.id,
                "location_dest_id": dest.id,
            },
        )
        move._action_confirm()
        if line_vals is None:
            move._action_assign()
        else:
            move.move_line_ids.unlink()
            move.move_line_ids = [
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "quantity": quantity,
                        "location_id": source.id,
                        "location_dest_id": dest.id,
                        **line_vals,
                    },
                )
            ]
        move.picked = True
        move._action_done()
        return move

    def _backdate(self, moves, days):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE stock_move SET date = now() - make_interval(days => %s)"
            " WHERE id = ANY(%s)",
            [days, moves.ids],
        )
        self.env.invalidate_all()


class TestQuantityAtDateFollowsTheLines(CatalogAuditCase):
    def test_a_sublocation_scope_counts_what_left_its_lines(self):
        shelf = self.Location.create(
            {"name": "Shelf at date", "location_id": self.stock.id}
        )
        product = self.Product.create({"name": "At date shelf", "is_storable": True})
        receipt = self._done_move(
            product,
            10,
            self.supplier,
            self.stock,
            line_vals={"location_dest_id": shelf.id},
        )
        self._backdate(receipt, 10)
        delivery = self._done_move(product, 10, self.stock, self.customer)
        self.assertEqual(delivery.move_line_ids.location_id, shelf)
        past = fields.Datetime.now() - datetime.timedelta(days=5)
        self.assertEqual(
            product.with_context(location=shelf.id, to_date=past).qty_available,
            10.0,
            "the delivery left the shelf although its move names the parent",
        )
        self.assertEqual(
            product.with_context(location=self.stock.id, to_date=past).qty_available,
            10.0,
        )

    def test_an_owner_scope_reads_the_owner_of_the_lines(self):
        owner = self.env["res.partner"].create({"name": "Consignor at date"})
        product = self.Product.create({"name": "At date owner", "is_storable": True})
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock, 10, owner_id=owner
        )
        self._done_move(
            product, 10, self.stock, self.customer, line_vals={"owner_id": owner.id}
        )
        yesterday = fields.Datetime.now() - datetime.timedelta(days=1)
        self.assertEqual(
            product.with_context(owner_id=owner.id, to_date=yesterday).qty_available,
            10.0,
            "the owner is on the line, the move carries no restrict_partner_id",
        )
        self.assertEqual(
            product.with_context(owner_id=False, to_date=yesterday).qty_available,
            0.0,
        )

    def test_a_lot_and_its_product_agree_on_a_bare_day(self):
        product = self.Product.create(
            {"name": "At date lot", "is_storable": True, "tracking": "lot"}
        )
        lot = self.Lot.create({"name": "AT-DATE-1", "product_id": product.id})
        self._done_move(
            product, 5, self.supplier, self.stock, line_vals={"lot_id": lot.id}
        )
        today = fields.Date.to_string(fields.Date.today())
        scoped = {"tz": "UTC", "to_date": today}
        self.assertEqual(product.with_context(**scoped).qty_available, 5.0)
        self.assertEqual(
            lot.with_context(**scoped).product_qty,
            5.0,
            "a bare day ends at the end of the reader's day for lots too",
        )

    def test_a_past_search_finds_stock_that_only_the_lines_saw(self):
        shelf = self.Location.create(
            {"name": "Shelf search", "location_id": self.stock.id}
        )
        product = self.Product.create({"name": "At date search", "is_storable": True})
        receipt = self._done_move(
            product,
            4,
            self.supplier,
            self.stock,
            line_vals={"location_dest_id": shelf.id},
        )
        self._backdate(receipt, 10)
        self._done_move(product, 4, self.stock, self.customer)
        past = fields.Datetime.now() - datetime.timedelta(days=5)
        found = self.Product.with_context(location=shelf.id, to_date=past).search(
            [("qty_available", ">", 0)]
        )
        self.assertIn(product, found)


class TestSearchCandidates(CatalogAuditCase):
    def test_done_history_alone_is_no_candidate_for_planned_quantities(self):
        product = self.Product.create({"name": "History only", "is_storable": True})
        self.env["stock.quant"]._update_available_quantity(product, self.stock, 3)
        self._done_move(product, 3, self.stock, self.customer)
        self.assertNotIn(
            product, self.Product._get_quantity_search_candidates(field="qty_incoming")
        )
        self.assertNotIn(
            product, self.Product._get_quantity_search_candidates(field="qty_outgoing")
        )
        self.assertIn(product, self.Product.search([("qty_incoming", "=", 0)]))

    def test_a_search_that_admits_zero_is_one_exclusion(self):
        stocked = self.Product.create({"name": "Admits zero", "is_storable": True})
        self.env["stock.quant"]._update_available_quantity(stocked, self.stock, 2)
        domain = self.Product._get_domain_product_quantity(
            "<=", 0, "qty_available_virtual"
        )
        self.assertEqual(len(domain), 1)
        field, operator, ids = domain[0]
        self.assertEqual((field, operator), ("id", "not in"))
        self.assertIn(stocked.id, ids)
        empty = self.Product.create({"name": "Admits zero empty", "is_storable": True})
        found = self.Product.search([("qty_available_virtual", "<=", 0)])
        self.assertIn(empty, found)
        self.assertNotIn(stocked, found)


class TestEmptyLocationSearch(CatalogAuditCase):
    def test_is_empty_is_a_subquery_not_a_materialized_list(self):
        full = self.Location.create(
            {"name": "Occupied bin", "location_id": self.stock.id}
        )
        empty = self.Location.create(
            {"name": "Empty bin", "location_id": self.stock.id}
        )
        product = self.Product.create({"name": "Occupant", "is_storable": True})
        self.env["stock.quant"]._update_available_quantity(product, full, 1)
        self.env.flush_all()
        before = self.env.cr.sql_statement_count
        domain = self.Location._search_is_empty("in", [True])
        self.assertEqual(
            self.env.cr.sql_statement_count, before, "building the domain reads nothing"
        )
        self.assertNotIsInstance(domain[0][2], list)
        found = self.Location.search([("is_empty", "=", True)])
        self.assertIn(empty, found)
        self.assertNotIn(full, found)


class TestEmptyOnlyStorage(CatalogAuditCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        category = cls.env["stock.storage.category"].create(
            {"name": "Empty only", "allow_new_product": "empty"}
        )
        cls.bins = cls.Location.create(
            [
                {
                    "name": f"Empty only bin {index}",
                    "location_id": cls.stock.id,
                    "storage_category_id": category.id,
                }
                for index in range(3)
            ]
        )
        cls.serial = cls.Product.create(
            {"name": "Empty only serial", "is_storable": True, "tracking": "serial"}
        )
        cls.env["stock.putaway.rule"].create(
            {
                "location_in_id": cls.stock.id,
                "location_out_id": cls.stock.id,
                "product_id": cls.serial.id,
                "storage_category_id": category.id,
                "sublocation": "closest_location",
            }
        )

    def test_a_batch_does_not_fill_an_empty_only_bin_twice(self):
        locations = self.stock._get_putaway_strategy_batch(self.serial, [1, 1, 1])
        self.assertEqual(
            [location.id for location in locations],
            self.bins.ids,
            "a bin that received the first serial is no longer empty",
        )

    def test_goods_on_their_way_in_make_a_bin_non_empty(self):
        move = self.env["stock.move"].create(
            {
                "product_id": self.serial.id,
                "product_uom_qty": 1,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock.id,
            }
        )
        move._action_confirm()
        move.move_line_ids.location_dest_id = self.bins[0]
        self.assertEqual(move.move_line_ids.location_dest_id, self.bins[0])
        self.assertEqual(
            self.stock._get_putaway_strategy(self.serial, quantity=1), self.bins[1]
        )
        self.assertEqual(
            self.stock.with_context(
                exclude_sml_ids=set(move.move_line_ids.ids)
            )._get_putaway_strategy(self.serial, quantity=1),
            self.bins[0],
            "the line being placed does not occupy its own bin",
        )


class TestLotNameFormatEverywhere(CatalogAuditCase):
    def _formatted(self, lot_format):
        return self.Product.create(
            {
                "name": f"Formatted {lot_format}",
                "is_storable": True,
                "tracking": "lot",
                "lot_name_format": lot_format,
            }
        )

    def test_the_next_lot_vals_follow_the_format(self):
        product = self._formatted("LF-%(ref)s")
        vals = self.Lot._prepare_next_lot_vals(self.env.company, product)
        self.assertTrue(vals["name"].startswith("LF-"), vals["name"])
        self.assertEqual(
            self.Lot.create({"product_id": product.id}).name[:3],
            "LF-",
        )

    def test_a_format_without_ref_cannot_keep_names_apart(self):
        with self.assertRaises(ValidationError):
            self._formatted("M-%(year)s%(month)s")
        product = self._formatted("M-%(ref)s")
        with self.assertRaises(ValidationError):
            product.lot_name_format = "M-%(year)s"

    def test_a_free_name_skips_an_archived_lot(self):
        product = self.Product.create(
            {"name": "Free name", "is_storable": True, "tracking": "serial"}
        )
        self.Lot.create({"name": "FREE0001", "product_id": product.id})
        archived = self.Lot.create({"name": "FREE0002", "product_id": product.id})
        archived.active = False
        self.env.flush_all()
        self.assertEqual(
            self.Lot._get_free_lot_name(self.env.company, product, "FREE0001"),
            "FREE0003",
        )


class TestForecastSharesTheQuantityScope(CatalogAuditCase):
    def test_an_incoming_move_through_transit_is_a_report_line(self):
        transit = self.Location.create({"name": "Forecast transit", "usage": "transit"})
        product = self.Product.create({"name": "Forecast final", "is_storable": True})
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 7,
                "location_id": self.supplier.id,
                "location_dest_id": transit.id,
                "location_final_id": self.stock.id,
            }
        )
        move._action_confirm()
        report = self.env["stock.forecasted_product_product"].with_context(
            warehouse_id=self.warehouse.id
        )
        data = report._get_report_data(product_ids=product.ids)
        self.assertEqual(data["product"][product.id]["qty_incoming"], 7.0)
        incoming = [line for line in data["lines"] if line["move_in"]]
        self.assertEqual(
            [line["quantity"] for line in incoming],
            [7.0],
            "the header counts it incoming, so the lines must show it",
        )


@tagged("post_install", "-at_install")
class TestScrapLocationPerCompany(CatalogAuditCase):
    def test_a_new_company_gets_its_designated_scrap_location(self):
        company = self.env["res.company"].create({"name": "Scrap Co"})
        scrap_location = company._get_scrap_location()
        self.assertTrue(scrap_location)
        self.assertEqual(scrap_location.usage, "inventory")
        self.assertEqual(scrap_location.company_id, company)
        inventory_loss = self.Location.search(
            [("company_id", "=", company.id), ("usage", "=", "inventory")],
            order="id",
            limit=1,
        )
        self.assertNotEqual(scrap_location, inventory_loss)
        scrap = (
            self.env["stock.scrap"]
            .with_company(company)
            .new(
                {
                    "company_id": company.id,
                    "product_id": self.Product.create({"name": "S"}).id,
                }
            )
        )
        self.assertEqual(scrap.scrap_location_id, scrap_location)

    def test_the_missing_path_adopts_a_pre_existing_scrap_location(self):
        company = self.env["res.company"].create({"name": "Scrap Adopt Co"})
        designated = company._get_scrap_location()
        self.env["ir.model.data"].search(
            [("model", "=", "stock.location"), ("res_id", "=", designated.id)]
        ).unlink()
        self.assertFalse(company._get_scrap_location())
        self.env["res.company"].create_missing_scrap_location()
        self.assertEqual(company._get_scrap_location(), designated)

    def test_the_migration_designates_one_for_every_company(self):
        company = self.env["res.company"].create({"name": "Scrap Migrate Co"})
        designated = company._get_scrap_location()
        self.env["ir.model.data"].search(
            [("model", "=", "stock.location"), ("res_id", "=", designated.id)]
        ).unlink()
        designated.name = "Old losses"
        script = load_script(
            f"{get_module_path('stock')}/migrations/1.20/post-migrate.py",
            "stock_1_20_post_migrate",
        )
        script.migrate(self.env.cr, "1.19")
        self.env.invalidate_all()
        created = company._get_scrap_location()
        self.assertTrue(created)
        self.assertNotEqual(created, designated)
        self.assertEqual(created.name, "Scrap")


class TestNoDeadLotHelpers(TransactionCase):
    def test_the_unused_lot_helpers_are_gone(self):
        self.assertFalse(hasattr(self.env["stock.lot"], "_get_next_serial"))
        self.assertFalse(hasattr(self.env["stock.lot"], "_parse_name"))

    def test_the_generate_serials_dialog_previews_without_drawing(self):
        product = self.env["product.product"].create(
            {"name": "preview", "is_storable": True, "tracking": "serial"}
        )
        preview = product.get_next_lot_preview()
        self.assertTrue(preview)
        self.assertEqual(product.get_next_lot_preview(), preview)
