import datetime

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class ExpiryAuditCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")
        cls.product = cls.env["product.product"].create(
            {
                "name": "Audit Yoghurt",
                "is_storable": True,
                "tracking": "lot",
                "use_expiration_date": True,
                "expiration_time": 30,
                "use_time": 2,
                "removal_time": 5,
                "alert_time": 10,
            }
        )

    def _lot(self, name, expiration_offset_days):
        return self.env["stock.lot"].create(
            {
                "name": name,
                "product_id": self.product.id,
                "expiration_date": fields.Datetime.now()
                + datetime.timedelta(days=expiration_offset_days),
            }
        )

    def _delivery(self, lot, qty=5.0):
        self.env["stock.quant"]._update_available_quantity(
            self.product, self.stock_location, qty, lot_id=lot
        )
        self.env.flush_all()
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": qty,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        self.env.flush_all()
        for move_line in picking.move_line_ids:
            move_line.quantity = qty
        picking.move_ids.picked = True
        self.env.flush_all()
        return picking


class TestExpiryDerivedDates(ExpiryAuditCommon):
    def test_a_write_re_derives_the_dependent_dates(self):
        lot = self._lot("AUDIT-W", 30)
        self.env.flush_all()
        lot.write(
            {"expiration_date": fields.Datetime.now() + datetime.timedelta(days=60)}
        )
        self.env.flush_all()
        self.assertEqual(lot.use_date, lot.expiration_date - datetime.timedelta(days=2))
        self.assertEqual(
            lot.removal_date, lot.expiration_date - datetime.timedelta(days=5)
        )
        self.assertEqual(
            lot.alert_date, lot.expiration_date - datetime.timedelta(days=10)
        )

    def test_a_form_and_a_write_agree(self):
        target = fields.Datetime.now() + datetime.timedelta(days=60)
        written = self._lot("AUDIT-CMP-W", 30)
        self.env.flush_all()
        written.write({"expiration_date": target})

        formed = self._lot("AUDIT-CMP-F", 30)
        self.env.flush_all()
        with Form(formed) as form:
            form.expiration_date = target
        self.env.flush_all()

        for field in ("use_date", "removal_date", "alert_date"):
            self.assertEqual(
                written[field],
                formed[field],
                f"{field} must not depend on whether the date was set in a form",
            )

    def test_clearing_the_expiration_date_clears_the_derived_dates(self):
        lot = self._lot("AUDIT-CLR", 30)
        self.env.flush_all()
        lot.write({"expiration_date": False})
        self.env.flush_all()
        self.assertFalse(lot.use_date)
        self.assertFalse(lot.removal_date)
        self.assertFalse(
            lot.removal_date,
            "a lot with no expiration date is non-perishable and must not keep a"
            " removal date that would make its stock unreservable",
        )
        self.assertFalse(lot.alert_date)

    def test_extending_shelf_life_makes_the_stock_reservable_again(self):
        lot = self._lot("AUDIT-EXT", -1)
        self.env.flush_all()
        self.assertFalse(
            self._delivery(lot).move_line_ids, "expired stock must not reserve"
        )

        lot.write(
            {"expiration_date": fields.Datetime.now() + datetime.timedelta(days=59)}
        )
        self.env.flush_all()
        self.assertTrue(
            self._delivery(lot).move_line_ids,
            "once the shelf life is extended the stock must reserve again",
        )

    def test_the_derived_dates_follow_the_product_flag(self):
        lot = self._lot("AUDIT-FLAG", 30)
        self.env.flush_all()
        self.product.use_expiration_date = False
        self.env.flush_all()
        self.assertFalse(lot.removal_date)


class TestExpiryClock(ExpiryAuditCommon):
    def test_the_computed_expiration_date_uses_the_orm_clock(self):
        lot = self.env["stock.lot"].create(
            {"name": "AUDIT-CLOCK", "product_id": self.product.id}
        )
        self.env.flush_all()
        self.assertEqual(lot.expiration_date.microsecond, 0)
        expected = fields.Datetime.now() + datetime.timedelta(days=30)
        self.assertLess(
            abs(lot.expiration_date - expected), datetime.timedelta(minutes=1)
        )

    def test_an_explicit_expiration_date_survives_a_product_change(self):
        other = self.env["product.product"].create(
            {
                "name": "Audit Other",
                "is_storable": True,
                "tracking": "lot",
                "use_expiration_date": True,
                "expiration_time": 3,
            }
        )
        lot = self.env["stock.lot"].create(
            {"name": "AUDIT-PROD", "product_id": self.product.id}
        )
        lot.product_id = other
        self.env.flush_all()
        expected = fields.Datetime.now() + datetime.timedelta(days=3)
        self.assertLess(
            abs(lot.expiration_date - expected),
            datetime.timedelta(minutes=1),
            "changing the product re-derives the date from the new product",
        )


class TestExpiryConfirmation(ExpiryAuditCommon):
    def _wizard_for(self, picking, action):
        return (
            self.env["expiry.picking.confirmation"]
            .with_context(
                **dict(action["context"], button_validate_picking_ids=picking.ids)
            )
            .create({})
        )

    def test_the_wizard_flags_exactly_what_the_button_removes(self):
        lot = self._lot("AUDIT-LOCK", -2)
        self.env.flush_all()
        lot.write({"removal_date": False})
        self.env.flush_all()
        picking = self._delivery(lot)
        action = picking.button_validate()
        self.assertEqual(action["res_model"], "expiry.picking.confirmation")
        wizard = self._wizard_for(picking, action)
        self.assertEqual(
            wizard.picking_ids.move_line_ids._filtered_expired(),
            picking.move_line_ids,
            "every line the wizard was raised for must be one the button can remove",
        )

    def test_an_entirely_expired_transfer_says_so(self):
        lot = self._lot("AUDIT-ALL", -2)
        self.env.flush_all()
        lot.write({"removal_date": False})
        self.env.flush_all()
        picking = self._delivery(lot)
        action = picking.button_validate()
        wizard = self._wizard_for(picking, action)
        with self.assertRaises(UserError):
            wizard.process_no_expired()

    def test_proceed_except_expired_keeps_the_fresh_lines(self):
        fresh = self._lot("AUDIT-FRESH", 30)
        stale = self._lot("AUDIT-STALE", -2)
        self.env.flush_all()
        stale.write({"removal_date": False})
        self.env.flush_all()
        for lot in (fresh, stale):
            self.env["stock.quant"]._update_available_quantity(
                self.product, self.stock_location, 5.0, lot_id=lot
            )
        self.env.flush_all()
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 10.0,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        self.env.flush_all()
        picking.move_ids.picked = True
        self.env.flush_all()
        self.assertEqual(len(picking.move_line_ids), 2)
        action = picking.button_validate()
        self.assertEqual(action["res_model"], "expiry.picking.confirmation")
        self._wizard_for(picking, action).process_no_expired()
        self.env.flush_all()
        self.assertNotIn(
            stale, picking.move_line_ids.lot_id, "the expired lot must be dropped"
        )
        self.assertIn(fresh, picking.move_line_ids.lot_id, "the fresh lot must survive")

    def test_process_survives_a_context_without_the_wizard_defaults(self):
        lot = self._lot("AUDIT-CTX", -2)
        self.env.flush_all()
        wizard = self.env["expiry.picking.confirmation"].create(
            {"lot_ids": [Command.set(lot.ids)]}
        )
        picking = self._delivery(self._lot("AUDIT-CTX2", 30))
        wizard.with_context(button_validate_picking_ids=picking.ids).process()
        self.assertEqual(picking.state, "done")

    def test_the_validation_context_drops_the_wizard_defaults(self):
        wizard = (
            self.env["expiry.picking.confirmation"]
            .with_context(
                default_lot_ids=[Command.set([])],
                default_picking_ids=[Command.set([])],
                some_other_key=1,
            )
            .create({"lot_ids": [Command.set(self._lot("AUDIT-DEF", 30).ids)]})
        )
        context = wizard._validation_context()
        self.assertNotIn("default_lot_ids", context)
        self.assertNotIn("default_picking_ids", context)
        self.assertEqual(context["some_other_key"], 1)
        self.assertTrue(context["skip_expired"])

    def test_the_description_computes_over_several_wizards(self):
        lots = self._lot("AUDIT-D1", 30) + self._lot("AUDIT-D2", 30)
        wizards = self.env["expiry.picking.confirmation"].create(
            [
                {"lot_ids": [Command.set(lots[0].ids)]},
                {"lot_ids": [Command.set(lots.ids)]},
            ]
        )
        self.assertEqual(len(wizards.mapped("description")), 2)
        self.assertFalse(wizards[0].show_lots)
        self.assertTrue(wizards[1].show_lots)


class TestExpiryLotImport(ExpiryAuditCommon):
    def test_a_decimal_quantity_with_a_unit_is_not_a_crash(self):
        vals = self.env["stock.move"].split_lots("LOT1;1.5 kg\nLOT2;2.5 kg")
        self.assertEqual(len(vals), 2)

    def test_an_out_of_range_year_is_not_a_crash(self):
        vals = self.env["stock.move"].split_lots("LOT1;5;12/13/9999999999")
        self.assertEqual(len(vals), 1)
        self.assertNotIn("expiration_date", vals[0])

    def test_a_real_date_is_still_read(self):
        vals = self.env["stock.move"].split_lots("LOT1;5;12/31/2026")
        self.assertEqual(
            vals[0]["expiration_date"], datetime.datetime(2026, 12, 31, 0, 0)
        )

    def test_a_plain_quantity_is_still_read(self):
        vals = self.env["stock.move"].split_lots("LOT1;5")
        self.assertEqual(vals[0]["quantity"], 5.0)


class TestExpiryProductDelays(ExpiryAuditCommon):
    def test_a_negative_delay_is_refused(self):
        for field in ("expiration_time", "use_time", "removal_time", "alert_time"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.product.product_tmpl_id.write({field: -1})

    def test_one_formula_derives_the_expiration_date(self):
        from_date = fields.Datetime.now()
        self.assertEqual(
            self.product._get_expiration_date_from(from_date),
            from_date + datetime.timedelta(days=30),
        )

    def test_a_product_without_expiration_dates_derives_nothing(self):
        plain = self.env["product.product"].create(
            {"name": "Audit Bolt", "is_storable": True, "tracking": "none"}
        )
        self.assertFalse(plain._get_expiration_date_from())


class TestExpiryNewLotFromMoveLine(ExpiryAuditCommon):
    def test_an_edited_removal_date_reaches_the_new_lot(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.in_type_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 4,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        self.env.flush_all()
        move_line = picking.move_line_ids or self.env["stock.move.line"].create(
            {
                "move_id": picking.move_ids.id,
                "product_id": self.product.id,
                "quantity": 4,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        move_line.lot_name = "AUDIT-NEW"
        chosen = fields.Datetime.now() + datetime.timedelta(days=1)
        move_line.removal_date = chosen
        picking.move_ids.picked = True
        picking.button_validate()
        self.env.flush_all()
        lot = self.env["stock.lot"].search([("name", "=", "AUDIT-NEW")], limit=1)
        self.assertEqual(
            lot.removal_date,
            chosen,
            "the operator's removal date must not be discarded",
        )


class TestExpiryAlertScheduler(ExpiryAuditCommon):
    def _due_lots(self, count):
        lots = self.env["stock.lot"].create(
            [
                {
                    "name": f"AUDIT-ALERT-{index}",
                    "product_id": self.product.id,
                    "expiration_date": fields.Datetime.now()
                    - datetime.timedelta(days=1),
                }
                for index in range(count)
            ]
        )
        self.env.flush_all()
        return lots

    def test_only_lots_holding_internal_stock_are_reminded(self):
        lots = self._due_lots(4)
        stocked, bare = lots[:2], lots[2:]
        for lot in stocked:
            self.env["stock.quant"]._update_available_quantity(
                self.product, self.stock_location, 1.0, lot_id=lot
            )
        self.env.flush_all()
        self.env["stock.lot"]._alert_date_exceeded()
        self.env.flush_all()
        self.assertTrue(all(stocked.mapped("product_expiry_reminded")))
        self.assertFalse(any(bare.mapped("product_expiry_reminded")))
        self.assertEqual(
            self.env["mail.activity"].search_count(
                [("res_model", "=", "stock.lot"), ("res_id", "in", lots.ids)]
            ),
            2,
        )

    def test_a_lot_is_reminded_only_once(self):
        lot = self._due_lots(1)
        self.env["stock.quant"]._update_available_quantity(
            self.product, self.stock_location, 1.0, lot_id=lot
        )
        self.env.flush_all()
        self.env["stock.lot"]._alert_date_exceeded()
        self.env["stock.lot"]._alert_date_exceeded()
        self.env.flush_all()
        self.assertEqual(
            self.env["mail.activity"].search_count(
                [("res_model", "=", "stock.lot"), ("res_id", "in", lot.ids)]
            ),
            1,
        )

    def test_the_scheduler_scopes_the_alert_to_its_company(self):
        other_company = self.env["res.company"].create({"name": "Audit Other Co"})
        lot = self._due_lots(1)
        self.env["stock.quant"]._update_available_quantity(
            self.product, self.stock_location, 1.0, lot_id=lot
        )
        self.env.flush_all()
        self.env["stock.scheduler"]._alert_expired_lots(company_id=other_company.id)
        self.env.flush_all()
        self.assertFalse(
            lot.product_expiry_reminded,
            "a per-company scheduler run must not alert another company's lots",
        )

    def test_the_activities_are_batched_by_assignee(self):
        lots = self._due_lots(6)
        for lot in lots:
            self.env["stock.quant"]._update_available_quantity(
                self.product, self.stock_location, 1.0, lot_id=lot
            )
        self.env.flush_all()
        self.env.invalidate_all()
        calls = []
        original = type(self.env["stock.lot"]).activity_schedule

        def counting(records, *args, **kwargs):
            calls.append(len(records))
            return original(records, *args, **kwargs)

        self.patch(type(self.env["stock.lot"]), "activity_schedule", counting)
        self.env["stock.lot"]._alert_date_exceeded()
        self.env.flush_all()
        self.assertEqual(
            len(calls), 1, "six lots sharing one assignee must take one call, not six"
        )
        self.assertEqual(calls[0], 6)


class TestExpiryAvailableQuantity(ExpiryAuditCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fresh, cls.stale = cls.env["stock.lot"].create(
            [
                {
                    "name": "AVAIL-FRESH",
                    "product_id": cls.product.id,
                    "expiration_date": fields.Datetime.now()
                    + datetime.timedelta(days=30),
                },
                {
                    "name": "AVAIL-STALE",
                    "product_id": cls.product.id,
                    "expiration_date": fields.Datetime.now()
                    - datetime.timedelta(days=1),
                },
            ]
        )
        cls.env["stock.quant"].create(
            [
                {
                    "product_id": cls.product.id,
                    "location_id": cls.stock_location.id,
                    "quantity": 10.0,
                    "lot_id": cls.fresh.id,
                },
                {
                    "product_id": cls.product.id,
                    "location_id": cls.stock_location.id,
                    "quantity": 7.0,
                    "lot_id": cls.stale.id,
                },
            ]
        )
        cls.env.flush_all()

    def test_the_group_total_equals_its_own_rows(self):
        domain = [("product_id", "=", self.product.id)]
        quants = self.env["stock.quant"].search(domain)
        rows = sum(quants.mapped("available_quantity"))
        [(grouped,)] = self.env["stock.quant"]._read_group(
            domain, aggregates=["available_quantity:sum"]
        )
        self.assertEqual(rows, 10.0, "stock past its removal date is not available")
        self.assertEqual(
            grouped,
            rows,
            "the grouped header must not count stock the rows beneath it report as 0",
        )

    def test_grouping_by_location_agrees_too(self):
        domain = [("product_id", "=", self.product.id)]
        [(_location, grouped)] = self.env["stock.quant"]._read_group(
            domain, ["location_id"], ["available_quantity:sum"]
        )
        self.assertEqual(grouped, 10.0)


class TestExpiryForecastDomains(ExpiryAuditCommon):
    def test_the_expired_domain_is_the_complement_of_the_fresh_one(self):
        report = self.env["stock.forecasted_product_product"]
        locations = self.stock_location.ids
        base = report._get_domain_base_quant(locations, self.product)
        fresh = report._get_quant_domain(locations, self.product)
        expired = report._get_expired_quant_domain(locations, self.product)
        for leaf in base:
            self.assertIn(leaf, fresh)
            self.assertIn(
                leaf,
                expired,
                "the expired domain must keep every base restriction, including any"
                " another module adds",
            )

    def test_a_narrowing_of_the_base_reaches_the_expired_domain(self):
        report = self.env["stock.forecasted_product_product"]
        marker = ("company_id", "=", self.env.company.id)
        original = type(report)._get_domain_base_quant

        def narrowed(records, location_ids, products):
            return original(records, location_ids, products) + [marker]

        self.patch(type(report), "_get_domain_base_quant", narrowed)
        self.assertIn(
            marker,
            report._get_expired_quant_domain(self.stock_location.ids, self.product),
        )
        self.assertIn(
            marker, report._get_quant_domain(self.stock_location.ids, self.product)
        )


class TestExpiryCutoffIsAnInstant(ExpiryAuditCommon):
    def test_stock_removable_earlier_today_is_not_free(self):
        lot = self._lot("CUTOFF", 30)
        self.env.flush_all()
        self.env["stock.quant"].create(
            {
                "product_id": self.product.id,
                "location_id": self.stock_location.id,
                "quantity": 4.0,
                "lot_id": lot.id,
            }
        )
        self.env.flush_all()
        self.assertEqual(self.product.qty_free, 4.0)

        now = fields.Datetime.now()
        earlier_today = now.replace(hour=0, minute=1, second=0, microsecond=0)
        if earlier_today >= now:
            earlier_today = now - datetime.timedelta(minutes=1)
        lot.write({"removal_date": earlier_today})
        self.env.flush_all()
        self.product.invalidate_recordset()
        self.assertEqual(
            self.product.qty_free,
            0.0,
            "stock past its removal date must not be free, whatever the hour",
        )
