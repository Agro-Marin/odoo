from datetime import datetime, timedelta

from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tests import Form, tagged

from . import common


@tagged("-at_install", "post_install")
class TestProductivityDuration(common.TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workcenter = cls.workcenter_1
        cls.workcenter.resource_calendar_id.leave_ids.unlink()
        cls.env["mrp.workcenter.productivity"].search(
            [("workcenter_id", "=", cls.workcenter.id)]
        ).unlink()
        cls.blocking = cls.env.ref("mrp.block_reason0")
        cls.productive = cls.env.ref("mrp.block_reason7")

    def _log(self, loss, date_start, date_end):
        return self.env["mrp.workcenter.productivity"].create(
            {
                "workcenter_id": self.workcenter.id,
                "loss_id": loss.id,
                "date_start": date_start,
                "date_end": date_end,
            }
        )

    def test_editing_a_date_leaves_the_start_and_the_reason_alone(self):
        log = self._log(
            self.blocking, datetime(2026, 8, 14, 10, 0), datetime(2026, 8, 17, 10, 0)
        )
        self.assertEqual(log.duration, 480.0)
        with Form(log) as form:
            form.date_end = datetime(2026, 8, 18, 10, 0)
        self.assertEqual(
            log.date_start,
            datetime(2026, 8, 14, 10, 0),
            "extending the end date must not move the start date",
        )
        self.assertEqual(
            log.loss_id,
            self.blocking,
            "extending the end date must not rewrite the blocking reason",
        )
        self.assertEqual(log.duration, 960.0)

    def test_duration_follows_the_loss_reason(self):
        log = self._log(
            self.blocking, datetime(2026, 8, 14, 10, 0), datetime(2026, 8, 17, 10, 0)
        )
        self.assertEqual(log.duration, 480.0, "a block is measured on working time")
        log.loss_id = self.productive
        self.assertEqual(
            log.duration,
            4320.0,
            "switching to a productive reason switches the clock to wall time",
        )
        log.loss_id = self.blocking
        self.assertEqual(log.duration, 480.0)

    def test_duration_follows_the_workcenter_calendar(self):
        log = self._log(
            self.blocking, datetime(2026, 8, 14, 10, 0), datetime(2026, 8, 17, 10, 0)
        )
        self.assertEqual(log.duration, 480.0)
        self.workcenter.resource_calendar_id = False
        self.assertEqual(
            log.duration,
            4320.0,
            "with no calendar there is no working time to measure against",
        )

    def test_a_batch_of_durations_costs_one_calendar_read(self):
        base = datetime(2026, 8, 17, 6, 0)

        def make(count):
            return [
                {
                    "workcenter_id": self.workcenter.id,
                    "loss_id": self.blocking.id,
                    "date_start": base + timedelta(hours=index),
                    "date_end": base + timedelta(hours=index + 1),
                }
                for index in range(count)
            ]

        Productivity = self.env["mrp.workcenter.productivity"]
        cost = {}
        for count in (2, 20):
            Productivity.search([("workcenter_id", "=", self.workcenter.id)]).unlink()
            self.env.flush_all()
            self.env.invalidate_all()
            before = self.env.cr.sql_log_count
            Productivity.create(make(count))
            self.env.flush_all()
            cost[count] = self.env.cr.sql_log_count - before
        marginal = (cost[20] - cost[2]) / 18
        self.assertLess(
            marginal,
            1.5,
            "measuring 18 more durations must not cost a calendar read each: "
            "n=2 %s queries, n=20 %s queries" % (cost[2], cost[20]),
        )

    def test_two_open_timers_for_one_worker_are_refused(self):
        workorder = self.env["mrp.workorder"].search([], limit=1)
        self.env["mrp.workcenter.productivity"].create(
            {
                "workcenter_id": self.workcenter.id,
                "workorder_id": workorder.id,
                "loss_id": self.productive.id,
                "date_start": fields.Datetime.now(),
            }
        )
        with self.assertRaises(ValidationError):
            self.env["mrp.workcenter.productivity"].create(
                {
                    "workcenter_id": self.workcenter.id,
                    "workorder_id": workorder.id,
                    "loss_id": self.productive.id,
                    "date_start": fields.Datetime.now(),
                }
            )

    def test_the_loss_category_name_is_translated(self):
        lang = (
            self.env["res.lang"]
            .with_context(active_test=False)
            .search([("code", "=", "fr_FR")])
        )
        self.env["base.language.install"].create(
            {"lang_ids": [Command.set(lang.ids)]}
        ).lang_install()
        category = self.env.ref("mrp.category_availability")
        french = dict(
            category.with_context(lang="fr_FR")
            ._fields["loss_type"]
            ._description_selection(self.env(context={"lang": "fr_FR"}))
        )
        english = category.with_context(lang="en_US").display_name
        self.assertEqual(
            category.with_context(lang="fr_FR").display_name,
            french["availability"],
            "reading it in English first must not decide it for the French reader",
        )
        self.assertNotEqual(english, french["availability"])


@tagged("-at_install", "post_install")
class TestWorkcenterState(common.TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workcenter = cls.workcenter_1
        cls.env["mrp.workcenter.productivity"].search(
            [("workcenter_id", "=", cls.workcenter.id)]
        ).unlink()

    def _open(self, xmlid):
        return self.env["mrp.workcenter.productivity"].create(
            {
                "workcenter_id": self.workcenter.id,
                "loss_id": self.env.ref(xmlid).id,
                "date_start": fields.Datetime.now(),
            }
        )

    def test_blocked_wins_over_a_running_timer_either_way_round(self):
        for order in (
            ("mrp.block_reason7", "mrp.block_reason0"),
            ("mrp.block_reason0", "mrp.block_reason7"),
        ):
            with self.subTest(order=order):
                logs = self._open(order[0]) | self._open(order[1])
                self.assertEqual(
                    self.workcenter.working_state,
                    "blocked",
                    "a blocking log outranks a running timer whatever their ids",
                )
                logs.unlink()

    def test_unblock_leaves_a_running_timer_alone(self):
        running = self._open("mrp.block_reason7")
        blocking = self._open("mrp.block_reason0")
        self.assertEqual(self.workcenter.working_state, "blocked")
        self.workcenter.unblock()
        self.assertTrue(blocking.date_end, "the blocking log is closed")
        self.assertFalse(
            running.date_end,
            "unblocking must not close the work order timer that is still running",
        )

    def test_display_name_follows_the_working_state(self):
        workcenter = self.workcenter.with_context(
            group_by="workcenter_id", show_workcenter_status=True
        )
        self.assertNotIn("🔴", workcenter.display_name)
        self._open("mrp.block_reason0")
        self.assertIn(
            "🔴",
            workcenter.display_name,
            "the status marker must track working_state without an invalidation",
        )

    def test_the_status_marker_does_not_leak_to_a_plain_reader(self):
        plain = self.workcenter
        marked = self.workcenter.with_context(
            group_by="workcenter_id", show_workcenter_status=True
        )
        self.assertNotIn("🔴", plain.display_name)
        self._open("mrp.block_reason0")
        self.assertIn("🔴", marked.display_name)
        self.assertNotIn(
            "🔴",
            plain.display_name,
            "a reader who asked for no status marker must not inherit one",
        )


@tagged("-at_install", "post_install")
class TestWorkcenterDashboard(common.TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workcenter = cls.workcenter_1

    def test_the_capacity_line_is_one_week_of_the_calendar(self):
        week_range, date_start, date_stop = (
            self.workcenter._get_week_range_and_first_last_days()
        )
        one_week = self.workcenter.resource_calendar_id
        two_weeks = one_week.copy({"name": "Two weeks"})
        two_weeks.switch_calendar_type()
        self.assertEqual(one_week.hours_per_week, two_weeks.hours_per_week)
        graphs = {}
        for calendar in (one_week, two_weeks):
            self.workcenter.resource_calendar_id = calendar
            graphs[calendar] = self.workcenter._prepare_graph_data(
                self.workcenter._get_workcenter_load_per_week(
                    week_range, date_start, date_stop
                ),
                week_range,
            )[self.workcenter.id][0]["values"][1]
        self.assertEqual(
            graphs[one_week],
            graphs[two_weeks],
            "a two-week calendar has the same weekly capacity, not twice as much",
        )
        self.assertEqual(graphs[one_week], one_week.hours_per_week)

    def test_the_graph_does_not_leak_the_first_readers_language(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        english, french = (
            self.workcenter.with_context(lang="en_US"),
            self.workcenter.with_context(lang="fr_FR"),
        )
        self.env.invalidate_all()
        en_first = (english.kanban_dashboard_graph, french.kanban_dashboard_graph)
        self.env.invalidate_all()
        fr_second, en_second = (
            french.kanban_dashboard_graph,
            english.kanban_dashboard_graph,
        )
        self.assertEqual(
            en_first[0],
            en_second,
            "the English reader must get the same chart whoever read first",
        )
        self.assertEqual(en_first[1], fr_second)
        self.assertNotEqual(en_second, fr_second)

    def test_the_effectiveness_fields_take_one_query(self):
        workcenters = self.env["mrp.workcenter"].search([])
        self.env.invalidate_all()
        with self.assertQueryCount(__system__=1):
            workcenters.mapped("oee")
            workcenters.mapped("blocked_time")
            workcenters.mapped("productive_time")


@tagged("-at_install", "post_install")
class TestWorkcenterLate(common.TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workcenter = cls.workcenter_1
        cls.env["mrp.workorder"].search(
            [("workcenter_id", "=", cls.workcenter.id)]
        ).unlink()
        product = cls.env["product.product"].create(
            {"name": "Late probe", "is_storable": True}
        )
        bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1,
                "type": "normal",
                "operation_ids": [
                    Command.create(
                        {
                            "name": "Op",
                            "workcenter_id": cls.workcenter.id,
                            "time_cycle_manual": 60,
                        }
                    )
                ],
            }
        )
        cls.workorders = cls.env["mrp.workorder"]
        for date_start in (
            datetime(2026, 8, 21, 23, 0),
            datetime(2026, 8, 22, 3, 0),
            datetime(2026, 8, 30, 3, 0),
        ):
            production = cls.env["mrp.production"].create(
                {"product_id": product.id, "bom_id": bom.id, "product_qty": 1}
            )
            production.action_confirm()
            production.workorder_ids.date_start = date_start
            cls.workorders |= production.workorder_ids

    @freeze_time("2026-08-22 23:00:00")
    def test_the_late_count_does_not_depend_on_who_reads_it(self):
        counts = set()
        for tz in ("UTC", "Europe/Brussels", "America/Mexico_City", "Pacific/Auckland"):
            workcenter = self.workcenter.with_context(tz=tz)
            workcenter.invalidate_recordset()
            counts.add(workcenter.workorder_late_count)
        self.assertEqual(
            counts,
            {2},
            "late is a fact about the data, not about the reader's timezone",
        )

    @freeze_time("2026-08-22 23:00:00")
    def test_the_late_count_matches_the_filter_it_links_to(self):
        Workorder = self.env["mrp.workorder"]
        listed = Workorder.search(
            Domain("id", "in", self.workorders.ids) & Workorder._late_domain()
        )
        self.workcenter.invalidate_recordset()
        self.assertEqual(len(listed), self.workcenter.workorder_late_count)

    @freeze_time("2026-08-22 23:00:00")
    def test_the_search_view_filter_asks_the_same_question(self):
        Workorder = self.env["mrp.workorder"]
        by_field = Workorder.search(
            [("id", "in", self.workorders.ids), ("is_late", "=", True)]
        )
        by_domain = Workorder.search(
            Domain("id", "in", self.workorders.ids) & Workorder._late_domain()
        )
        self.assertEqual(
            by_field,
            by_domain,
            "the field the views filter on and the domain the badge counts "
            "must be one predicate",
        )
        self.assertEqual(
            by_field.mapped("is_late"),
            [True] * len(by_field),
            "and reading the field must agree with searching it",
        )
        self.assertFalse(
            (self.workorders - by_field).filtered("is_late"),
            "nothing outside the search reads as late",
        )
        not_late = Workorder.search(
            [("id", "in", self.workorders.ids), ("is_late", "=", False)]
        )
        self.assertEqual(
            not_late,
            self.workorders - by_field,
            "searching the negative must be the complement, not the same set: "
            "'= False' on a boolean reaches the search method as 'not in [True]'",
        )


@tagged("-at_install", "post_install")
class TestWorkcenterCapacity(common.TestMrpCommon):
    def test_a_capacity_line_inherits_the_workcenter_times(self):
        workcenter = self.workcenter_1
        workcenter.write({"time_start": 11.0, "time_stop": 13.0})
        product = self.env["product.product"].create({"name": "Cap probe"})
        workcenter.write(
            {
                "capacity_ids": [
                    Command.create({"product_id": product.id, "capacity": 3})
                ]
            }
        )
        capacity = workcenter.capacity_ids.filtered(lambda c: c.product_id == product)
        self.assertEqual(
            (capacity.time_start, capacity.time_stop),
            (11.0, 13.0),
            "a capacity line added through the work center takes its setup times",
        )

    def test_a_capacity_line_created_bare_still_inherits(self):
        workcenter = self.workcenter_2
        workcenter.write({"time_start": 7.0, "time_stop": 9.0})
        product = self.env["product.product"].create({"name": "Bare cap probe"})
        capacity = self.env["mrp.workcenter.capacity"].create(
            {"workcenter_id": workcenter.id, "product_id": product.id, "capacity": 2}
        )
        self.assertEqual((capacity.time_start, capacity.time_stop), (7.0, 9.0))


@tagged("-at_install", "post_install")
class TestWorkcenterCapacityLookup(common.TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workcenter = cls.workcenter_3
        cls.workcenter.write({"time_start": 3.0, "time_stop": 4.0})
        cls.workcenter.capacity_ids.unlink()
        cls.units = cls.env.ref("uom.product_uom_unit")
        cls.dozens = cls.env.ref("uom.product_uom_dozen")
        cls.product = cls.env["product.product"].create(
            {"name": "Ranked", "uom_id": cls.units.id}
        )
        cls.other = cls.env["product.product"].create(
            {"name": "Other ranked", "uom_id": cls.units.id}
        )

    def _capacity(self, product, unit, capacity, time_start):
        return self.env["mrp.workcenter.capacity"].create(
            {
                "workcenter_id": self.workcenter.id,
                "product_id": product.id,
                "product_uom_id": unit.id,
                "capacity": capacity,
                "time_start": time_start,
                "time_stop": 0.0,
            }
        )

    def test_no_line_falls_back_to_the_workcenter(self):
        self.assertEqual(
            self.workcenter._get_capacity(self.product, self.units, 7),
            (7, 3.0, 4.0),
            "with nothing configured the work center's own times apply",
        )

    def test_another_products_line_is_not_used(self):
        self._capacity(self.other, self.units, 5, 11.0)
        self.assertEqual(
            self.workcenter._get_capacity(self.product, self.units, 7), (7, 3.0, 4.0)
        )

    def test_the_products_own_line_outranks_the_generic_one(self):
        self._capacity(self.env["product.product"], self.units, 5, 11.0)
        self._capacity(self.product, self.units, 9, 22.0)
        self.assertEqual(
            self.workcenter._get_capacity(self.product, self.units, 7),
            (9, 22.0, 0.0),
        )

    def test_the_generic_line_applies_to_any_product(self):
        self._capacity(self.env["product.product"], self.units, 5, 11.0)
        self.assertEqual(
            self.workcenter._get_capacity(self.product, self.units, 7),
            (5, 11.0, 0.0),
        )

    def test_a_generic_line_in_the_asked_unit_outranks_one_in_the_products_unit(self):
        self._capacity(self.env["product.product"], self.units, 5, 11.0)
        self._capacity(self.env["product.product"], self.dozens, 2, 22.0)
        self.assertEqual(
            self.workcenter._get_capacity(self.product, self.dozens, 7)[1],
            22.0,
            "the line stated in the unit the caller asked for wins",
        )

    def test_the_capacity_is_converted_into_the_asked_unit(self):
        self._capacity(self.product, self.units, 24, 11.0)
        capacity, _setup, _cleanup = self.workcenter._get_capacity(
            self.product, self.dozens, 7
        )
        self.assertEqual(capacity, 2, "24 units is 2 dozen")

    def test_a_zero_capacity_means_fall_back_but_keep_the_times(self):
        self._capacity(self.product, self.units, 0, 11.0)
        self.assertEqual(
            self.workcenter._get_capacity(self.product, self.units, 7),
            (7, 11.0, 0.0),
            "zero is 'unset': the default quantity applies, the line's times still do",
        )

    def test_it_refuses_a_multi_record_set(self):
        with self.assertRaises(ValueError):
            (self.workcenter | self.workcenter_1)._get_capacity(
                self.product, self.units
            )
