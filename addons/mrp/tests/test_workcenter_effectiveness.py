import re
from datetime import datetime, timedelta

from freezegun import freeze_time
from lxml import etree

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tests import Form, tagged
from odoo.tools.safe_eval import safe_eval

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

    def _open_workorder(self):
        production = self.env["mrp.production"].create(
            {"product_id": self.product_4.id, "product_qty": 1}
        )
        production.action_confirm()
        return self.env["mrp.workorder"].create(
            {
                "name": "timer test",
                "production_id": production.id,
                "workcenter_id": self.workcenter.id,
                "product_uom_id": production.product_uom_id.id,
            }
        )

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
            before = self.env.cr.sql_statement_count
            Productivity.create(make(count))
            self.env.flush_all()
            cost[count] = self.env.cr.sql_statement_count - before
        marginal = (cost[20] - cost[2]) / 18
        self.assertLess(
            marginal,
            1.5,
            "measuring 18 more durations must not cost a calendar read each: "
            "n=2 %s queries, n=20 %s queries" % (cost[2], cost[20]),
        )

    def test_two_open_timers_for_one_worker_are_refused(self):
        workorder = self._open_workorder()
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
        ).action_install_lang()
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
        self.workcenter.action_unblock()
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
            Domain("id", "in", self.workorders.ids) & Workorder._get_domain_late()
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
            Domain("id", "in", self.workorders.ids) & Workorder._get_domain_late()
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
class TestProductionLate(common.TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.picking_type = cls.env.ref("stock.warehouse0").manu_type_id
        product = cls.env["product.product"].create({"name": "Late MO probe"})
        cls.productions = cls.env["mrp.production"].create(
            [
                {
                    "product_id": product.id,
                    "product_qty": 1,
                    "picking_type_id": cls.picking_type.id,
                }
                for _ in range(3)
            ]
        )
        cls.productions.action_confirm()
        for production, date_start in zip(
            cls.productions,
            (
                datetime(2026, 8, 21, 9, 0),
                datetime(2026, 8, 22, 10, 0),
                datetime(2026, 8, 23, 9, 0),
            ),
            strict=True,
        ):
            production.date_start = date_start

    def _listed_under_the_late_link(self):
        arch = self.env.ref("mrp.view_mrp_production_filter").arch
        [late] = etree.fromstring(arch).iterfind(".//filter[@name='filter_late_mo']")
        return self.env["mrp.production"].search(
            Domain("picking_type_id", "=", self.picking_type.id)
            & Domain(safe_eval(late.get("domain")))
        )

    @freeze_time("2026-08-22 16:00:00")
    def test_the_late_count_matches_the_list_it_opens(self):
        listed = self._listed_under_the_late_link()
        self.assertIn(
            self.productions[1],
            listed,
            "an order due earlier today is late",
        )
        self.picking_type.invalidate_recordset()
        self.assertEqual(self.picking_type.count_mo_late, len(listed))

    @freeze_time("2026-08-22 16:00:00")
    def test_reading_is_late_agrees_with_searching_it(self):
        late = self.env["mrp.production"].search(
            [("id", "in", self.productions.ids), ("is_late", "=", True)]
        )
        self.assertEqual(late, self.productions[:2])
        self.assertEqual(self.productions.mapped("is_late"), [True, True, False])
        self.assertEqual(
            self.env["mrp.production"].search(
                [("id", "in", self.productions.ids), ("is_late", "=", False)]
            ),
            self.productions[2],
        )


@tagged("-at_install", "post_install")
@freeze_time("2026-09-23 12:00:00")
class TestWorkcenterStatReports(common.TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workcenter = cls.workcenter_1
        cls.workcenter.resource_calendar_id.leave_ids.unlink()
        Productivity = cls.env["mrp.workcenter.productivity"]
        Productivity.search([("workcenter_id", "=", cls.workcenter.id)]).unlink()
        cls.env["mrp.workorder"].search(
            [("workcenter_id", "=", cls.workcenter.id)]
        ).unlink()
        Loss = cls.env["mrp.workcenter.productivity.loss"]
        now = fields.Datetime.now()
        cls.rows = Productivity.create(
            [
                {
                    "workcenter_id": cls.workcenter.id,
                    "loss_id": Loss._get_loss_of_type(loss_type).id,
                    "date_start": now - timedelta(days=days, minutes=minutes),
                    "date_end": now - timedelta(days=days),
                }
                for loss_type, days, minutes in (
                    ("productive", 3, 120),
                    ("performance", 2, 60),
                    ("availability", 1, 15),
                    ("quality", 5, 10),
                    ("availability", 70, 30),
                )
            ]
        )
        product = cls.env["product.product"].create({"name": "Stat probe"})
        bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": 1,
                "operation_ids": [
                    Command.create(
                        {
                            "name": name,
                            "workcenter_id": cls.workcenter.id,
                            "time_cycle_manual": minutes,
                        }
                    )
                    for name, minutes in (("First", 10), ("Second", 20))
                ],
            }
        )
        cls.env.user.group_ids += cls.env.ref("mrp.group_mrp_workorder_dependencies")
        bom.allow_operation_dependencies = True
        first, second = bom.operation_ids
        second.blocked_by_operation_ids = first
        production = cls.env["mrp.production"].create(
            {"product_id": product.id, "bom_id": bom.id, "product_qty": 1}
        )
        production.action_confirm()
        cls.open_workorders = production.workorder_ids
        done = cls.env["mrp.production"].create(
            {"product_id": product.id, "bom_id": bom.id, "product_qty": 1}
        )
        done.action_confirm()
        for workorder, minutes in zip(done.workorder_ids, (15, 25), strict=True):
            workorder.duration = minutes
        done.workorder_ids.button_finish()
        cls.done_workorders = done.workorder_ids

    def _click_stat(self, stat_field):
        workcenter = self.workcenter
        arch = workcenter.get_views([(False, "form")])["views"]["form"]["arch"]
        [button] = [
            node
            for node in etree.fromstring(arch).iter("button")
            if node.find(f".//field[@name='{stat_field}']") is not None
        ]
        eval_context = {"id": workcenter.id, "active_id": workcenter.id}
        eval_context["uid"] = self.env.uid
        button_context = safe_eval(button.get("context") or "{}", eval_context)
        if button.get("type") == "object":
            action = getattr(workcenter, button.get("name"))()
            return action, {**button_context, **(action.get("context") or {})}
        act = self.env["ir.actions.act_window"].browse(int(button.get("name")))
        action = {
            "res_model": act.res_model,
            "search_view_id": act.search_view_id.id,
            "domain": safe_eval(act.domain or "[]", eval_context),
        }
        return action, {
            **button_context,
            **safe_eval(act.context or "{}", eval_context),
        }

    def _listed(self, stat_field):
        action, context = self._click_stat(stat_field)
        Model = self.env[action["res_model"]]
        search_view = action.get("search_view_id")
        if isinstance(search_view, (list, tuple)):
            search_view = search_view[0]
        arch = Model.get_views([(search_view or False, "search")])["views"]["search"]
        root = etree.fromstring(arch["arch"])
        filter_names = {node.get("name") for node in root.iter("filter")}
        filter_groups, group = [], []
        for node in root:
            if node.tag == "separator" and group:
                filter_groups.append(group)
                group = []
            elif node.tag == "filter" and node.get("domain"):
                group.append(node)
        filter_groups.append(group)
        domain = Domain(action.get("domain") or [])
        for group in filter_groups:
            chosen = [
                n for n in group if context.get(f"search_default_{n.get('name')}")
            ]
            if chosen:
                domain &= Domain.OR(
                    Domain(safe_eval(n.get("domain"), {"uid": self.env.uid}))
                    for n in chosen
                )
        for key, value in context.items():
            if not key.startswith("search_default_") or not value:
                continue
            name = key.removeprefix("search_default_")
            if name in filter_names:
                continue
            self.assertTrue(
                name in Model._fields,
                f"{key} matches no filter and no field of {Model._name}",
            )
            domain &= Domain(name, "in", value if isinstance(value, list) else [value])
        return Model.search(domain)

    def test_the_oee_report_lists_what_the_oee_counts(self):
        rows = self._listed("oee")
        productive = sum(
            rows.filtered(
                lambda r: r.loss_type in ("productive", "performance")
            ).mapped("duration")
        )
        window = self.env["mrp.workcenter.productivity"].search(
            [
                ("workcenter_id", "=", self.workcenter.id),
                ("date_start", ">=", fields.Datetime.now() - timedelta(days=30)),
            ]
        )
        self.assertNotIn(
            self.rows[-1], rows, "the 70-day-old row is outside the window"
        )
        self.assertEqual(rows, window)
        self.assertAlmostEqual(
            self.workcenter.oee,
            round(productive * 100.0 / sum(rows.mapped("duration")), 2),
        )

    def test_the_lost_report_lists_the_lost_hours(self):
        rows = self._listed("blocked_time")
        self.assertEqual(
            set(rows.mapped("loss_type")),
            {"availability", "quality"},
            "performance losses are counted as productive time",
        )
        self.assertAlmostEqual(
            self.workcenter.blocked_time, sum(rows.mapped("duration")) / 60.0, places=2
        )

    def test_the_load_report_lists_the_open_workorders(self):
        self.assertEqual(
            set(self.open_workorders.mapped("state")), {"ready", "blocked"}
        )
        rows = self._listed("workcenter_load")
        self.assertEqual(rows, self.open_workorders)
        self.assertAlmostEqual(
            self.workcenter.workcenter_load, sum(rows.mapped("duration_expected"))
        )

    def test_the_performance_report_lists_the_done_workorders(self):
        rows = self._listed("performance")
        self.assertEqual(rows, self.done_workorders)
        self.assertAlmostEqual(
            self.workcenter.performance,
            100 * sum(rows.mapped("duration_expected")) / sum(rows.mapped("duration")),
            delta=1,
        )

    def test_every_workorder_link_names_a_filter(self):
        search = self.env["mrp.workorder"].get_views(
            [(self.env.ref("mrp.view_mrp_production_work_order_search").id, "search")]
        )["views"]["search"]["arch"]
        names = {
            node.get("name")
            for node in etree.fromstring(search).iter("filter", "field")
        }
        for view in ("mrp.mrp_workcenter_kanban", "mrp.mrp_workcenter_view"):
            arch = etree.fromstring(self.env.ref(view).arch)
            for node in arch.iter("a", "button"):
                context = node.get("context") or ""
                for key in re.findall(r"search_default_(\w+)", context):
                    self.assertIn(key, names, f"{view} {node.get('name')}: {context}")


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
