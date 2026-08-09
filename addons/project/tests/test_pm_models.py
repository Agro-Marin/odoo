"""Coverage for previously-untested fork PM models + the 1.8 DB constraints.

Before this file, project.sprint / project.baseline / project.gate /
project.risk / project.retrospective had zero behavioural tests. These lock in
the invariants (one current baseline, one active sprint, cross-project gate
milestone, retrospective non-cyclic chain) and the core computes.
"""

from datetime import timedelta

from lxml import etree
from psycopg import IntegrityError

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger
from odoo.tools.safe_eval import safe_eval

from odoo.addons.project.tests.test_project_base import TestProjectCommon


@tagged("-at_install", "post_install")
class TestPmModels(TestProjectCommon):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.today = fields.Date.today()

    # ----- project.baseline -------------------------------------------------
    def test_baseline_single_current_db_constraint(self) -> None:
        Baseline = self.env["project.baseline"]
        Baseline.create(
            {
                "name": "B1",
                "project_id": self.project_pigs.id,
                "is_current": True,
            }
        )
        with mute_logger("odoo.db.cursor"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                Baseline.create(
                    {
                        "name": "B2",
                        "project_id": self.project_pigs.id,
                        "is_current": True,
                    }
                )
                self.env.flush_all()

    def test_baseline_action_set_current_unsets_prior(self) -> None:
        Baseline = self.env["project.baseline"]
        b1 = Baseline.create(
            {
                "name": "B1",
                "project_id": self.project_pigs.id,
                "is_current": True,
            }
        )
        b2 = Baseline.create({"name": "B2", "project_id": self.project_pigs.id})
        b2.action_set_current()
        self.assertFalse(b1.is_current)
        self.assertTrue(b2.is_current)

    def test_baseline_snapshot_fidelity_and_double_capture(self) -> None:
        task = self.env["project.task"].create(
            {
                "name": "Snap me",
                "project_id": self.project_goats.id,
                "date_end": fields.Datetime.now(),
                "step_id": self.project_goats.workflow_step_ids[0].id,
            }
        )
        baseline = self.env["project.baseline"].create(
            {
                "name": "Snapshot",
                "project_id": self.project_goats.id,
            }
        )
        baseline.action_capture_snapshot()
        self.assertEqual(len(baseline.line_ids), len(self.project_goats.tasks))
        line = baseline.line_ids.filtered(lambda ln: ln.task_id == task)
        self.assertEqual(line.task_name, "Snap me")
        self.assertEqual(line.step_id, task.step_id)
        self.assertEqual(line.planned_end, task.date_end)
        # Re-capturing on the same baseline is rejected.
        with self.assertRaises(UserError):
            baseline.action_capture_snapshot()

    # ----- project.sprint ---------------------------------------------------
    def _make_sprint(self, name, state="planning"):
        return self.env["project.sprint"].create(
            {
                "name": name,
                "project_id": self.project_pigs.id,
                "date_start": self.today,
                "date_end": self.today + timedelta(days=14),
                "state": state,
            }
        )

    def test_sprint_single_active_db_constraint(self) -> None:
        self._make_sprint("S1", state="active")
        with mute_logger("odoo.db.cursor"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._make_sprint("S2", state="active")
                self.env.flush_all()

    def test_sprint_action_start_guard(self) -> None:
        self._make_sprint("S1", state="active")
        s2 = self._make_sprint("S2")
        with self.assertRaises(ValidationError):
            s2.action_start()

    def test_sprint_action_close_releases_open_tasks(self) -> None:
        sprint = self._make_sprint("S1", state="active")
        open_task = self.env["project.task"].create(
            {
                "name": "Open",
                "project_id": self.project_pigs.id,
                "state": "in_progress",
            }
        )
        done_task = self.env["project.task"].create(
            {
                "name": "Done",
                "project_id": self.project_pigs.id,
                "state": "done",
            }
        )
        sprint.task_ids = open_task + done_task
        self.assertEqual(open_task.sprint_id, sprint)
        sprint.action_close()
        self.assertEqual(sprint.state, "closed")
        self.assertFalse(open_task.sprint_id, "open task is released on close")
        self.assertEqual(done_task.sprint_id, sprint, "closed task stays for history")

    def test_sprint_task_metrics(self) -> None:
        sprint = self._make_sprint("S1")
        t_open = self.env["project.task"].create(
            {
                "name": "O",
                "project_id": self.project_pigs.id,
                "state": "in_progress",
                "planned_hours": 4.0,
            }
        )
        t_done = self.env["project.task"].create(
            {
                "name": "D",
                "project_id": self.project_pigs.id,
                "state": "done",
                "planned_hours": 6.0,
            }
        )
        sprint.task_ids = t_open + t_done
        self.assertEqual(sprint.task_count, 2)
        self.assertEqual(sprint.completed_count, 1)
        self.assertEqual(sprint.completion_pct, 50.0)
        self.assertEqual(sprint.committed_hours, 10.0)
        self.assertEqual(sprint.velocity, 6.0)

    # ----- project.gate -----------------------------------------------------
    def test_gate_milestone_must_match_project(self) -> None:
        self.project_pigs.allow_milestones = True
        self.project_goats.allow_milestones = True
        foreign_milestone = self.env["project.milestone"].create(
            {
                "name": "Foreign",
                "project_id": self.project_goats.id,
            }
        )
        with self.assertRaises(ValidationError):
            self.env["project.gate"].create(
                {
                    "name": "Gate",
                    "project_id": self.project_pigs.id,
                    "milestone_id": foreign_milestone.id,
                }
            )

    # ----- project.retrospective -------------------------------------------
    def test_retrospective_no_self_cycle(self) -> None:
        retro = self.env["project.retrospective"].create(
            {
                "name": "R1",
                "project_id": self.project_pigs.id,
            }
        )
        with self.assertRaises(ValidationError):
            retro.previous_id = retro

    def test_retrospective_carry_forward(self) -> None:
        r1 = self.env["project.retrospective"].create(
            {
                "name": "R1",
                "project_id": self.project_pigs.id,
            }
        )
        Action = self.env["project.retrospective.action"]
        owner = self.user_projectuser.id
        Action.create(
            {
                "name": "Open action",
                "retrospective_id": r1.id,
                "state": "open",
                "owner_id": owner,
            }
        )
        Action.create(
            {
                "name": "Done action",
                "retrospective_id": r1.id,
                "state": "done",
                "owner_id": owner,
            }
        )
        r2 = self.env["project.retrospective"].create(
            {
                "name": "R2",
                "project_id": self.project_pigs.id,
                "previous_id": r1.id,
            }
        )
        r2.action_carry_forward()
        self.assertEqual(len(r2.action_ids), 1, "only open actions carry forward")
        self.assertEqual(r2.action_ids.name, "Open action")

    # ----- project.pm.mixin -------------------------------------------------
    def test_pm_mixin_copy_appends_copy_suffix(self) -> None:
        """The shared mixin must append '(copy)' on duplicate for every model
        that used to carry its own copy_data override."""
        step = self.env["project.workflow.step"].create({"name": "Backlog"})
        phase = self.env["project.phase"].create({"name": "Planning"})
        role = self.env["project.role"].create({"name": "Reviewer"})
        triage = self.env["project.triage"].create(
            {
                "name": "Today",
                "user_id": self.user_projectuser.id,
            }
        )
        self.assertEqual(step.copy().name, "Backlog (copy)")
        self.assertEqual(phase.copy().name, "Planning (copy)")
        self.assertEqual(role.copy().name, "Reviewer (copy)")
        self.assertEqual(triage.copy().name, "Today (copy)")

    # ----- project.risk -----------------------------------------------------
    def test_risk_score_level_boundaries(self) -> None:
        Risk = self.env["project.risk"]
        cases = [
            ("1", "4", 4, "low"),  # 4  -> low  (below 5)
            ("1", "5", 5, "medium"),  # 5  -> medium (boundary)
            ("3", "3", 9, "medium"),  # 9  -> medium (below 10)
            ("2", "5", 10, "high"),  # 10 -> high (boundary)
            ("3", "5", 15, "high"),  # 15 -> high (below 16)
            ("4", "4", 16, "critical"),  # 16 -> critical (boundary)
        ]
        for prob, impact, score, level in cases:
            risk = Risk.create(
                {
                    "name": f"R{score}",
                    "project_id": self.project_pigs.id,
                    "probability": prob,
                    "impact": impact,
                }
            )
            self.assertEqual(risk.risk_score, score)
            self.assertEqual(
                risk.risk_level, level, f"prob={prob} impact={impact} score={score}"
            )


@tagged("-at_install", "post_install")
class TestPortfolioViews(TestProjectCommon):
    """The portfolio views must only sort and aggregate on stored columns.

    `_compute_health_indicators` documents that its fields are deliberately
    non-reactive and "cannot be searched or grouped". Anything the ORM has to
    push into SQL -- an `order`, a `read_group` aggregate -- therefore raises
    `Cannot convert ... to SQL because it is not stored`, and the view that
    asked for it fails to open at all rather than degrading.
    """

    def test_portfolio_list_default_order_is_stored(self):
        """The list view's default_order must be readable."""
        view = self.env.ref("project.project_portfolio_list")
        order = etree.fromstring(view.arch).get("default_order")
        self.assertTrue(order, "the portfolio list should declare a default_order")
        # Raises if any component of the order is a non-stored field.
        self.env["project.project"].search([], order=order, limit=5)

    def test_portfolio_health_fields_are_aggregatable(self):
        """The tripwire fired, and this is the revisit it asked for.

        This used to assert the opposite: that health_score must stay unstored,
        with the note "if health_score ever becomes stored this fails, which is
        the moment to revisit the graph and pivot measures rather than discover
        it in a view". That moment came. Unstored, the fields could not be
        filtered, grouped or sorted at all — ``Cannot convert
        project.project.health_status to SQL because it is not stored`` — which
        is most of what a health indicator is for: "show me every project that
        is off track" is a search. They are stored snapshots now, refreshed by
        ``_cron_refresh_metrics``, so aggregating them is legal and the general
        guard below is what keeps the views honest.
        """
        Project = self.env["project.project"]
        for fname in Project._SNAPSHOT_METRIC_FIELDS:
            self.assertTrue(
                Project._fields[fname].store,
                f"{fname} must stay stored: the portfolio views measure it",
            )
        # Both directions of the contract: aggregatable, and searchable.
        Project._read_group([], ["health_status"], ["health_score:avg"])
        Project.search([], order="health_score desc", limit=5)

    def test_reachable_aggregating_views_measure_stored_fields(self):
        """No action may offer a graph/pivot that measures a non-stored field.

        `read_group` pushes every measure into SQL, so a non-stored compute
        cannot be aggregated at all -- the view opens on an error dialog rather
        than on empty data. This is the general form of the portfolio bug, and
        what made it easy to miss: the same field renders perfectly well in a
        list, so it looks usable.

        Checked through the actions rather than the views, because that is what
        decides reachability: a view record kept around for future work is
        harmless until something offers it.
        """
        Project = self.env["project.project"]
        actions = self.env["ir.actions.act_window"].search(
            [("res_model", "=", "project.project")]
        )
        self.assertTrue(actions, "expected act_window actions on project.project")
        offenders = []
        for action in actions:
            # `views` federates view_mode / view_ids / view_id, so it is the
            # pair the client actually opens.
            for view_id, mode in action.views:
                if mode not in ("graph", "pivot"):
                    continue
                arch = Project.get_view(view_id=view_id or None, view_type=mode)["arch"]
                for node in etree.fromstring(arch).iter("field"):
                    if node.get("type") != "measure":
                        continue
                    field = Project._fields.get(node.get("name"))
                    if field is not None and not field.store:
                        offenders.append(
                            f"{action.xml_id or action.name}/{mode}:{node.get('name')}"
                        )
        self.assertFalse(
            offenders,
            "actions offering a view that aggregates a non-stored field: "
            + ", ".join(offenders),
        )


@tagged("-at_install", "post_install")
class TestProjectActionsOpen(TestProjectCommon):
    """Every act_window this module ships must survive being opened.

    The browser sweep that would catch this (`TestMenusAdmin`, tag
    `click_all`) is `-standard`, so it never runs; the one that does
    (`TestMenusAdminLight`) stops at each app's landing action and cannot
    reach a submenu. That leaves the fork's PM menus — portfolio, sprints,
    baselines, gates, risks, retrospectives — with no coverage of the one
    thing a user does first: open them.

    This is the cheap ORM-level half: it performs, per declared view mode, the
    read the client would issue. It does not render anything, so it catches
    what fails in SQL (an `order` or a measure over a non-stored compute), not
    what fails in a template.
    """

    def test_every_project_action_opens(self):
        actions = self.env["ir.actions.act_window"].search([])
        actions = actions.filtered(
            lambda a: (
                (a.xml_id or "").startswith("project.") and a.res_model in self.env
            )
        )
        self.assertTrue(actions, "expected act_window actions from project")
        failures = []
        for action in actions:
            model = self.env[action.res_model]
            for view_id, mode in action.views:
                if mode not in ("list", "graph", "pivot"):
                    continue
                try:
                    arch = etree.fromstring(
                        model.get_view(view_id=view_id or None, view_type=mode)["arch"]
                    )
                    if mode == "list":
                        order = arch.get("default_order")
                        if order:
                            model.search([], order=order, limit=1)
                    else:
                        measures = [
                            f"{n.get('name')}:sum"
                            for n in arch.iter("field")
                            if n.get("type") == "measure"
                        ]
                        if measures:
                            model.formatted_read_group([], aggregates=measures)
                except Exception as exc:
                    failures.append(
                        f"{action.xml_id}/{mode}: {type(exc).__name__}: {str(exc)[:90]}"
                    )
        self.assertFalse(
            failures, "actions that fail to open:\n  " + "\n  ".join(failures)
        )

    def test_menu_reachable_action_contexts_evaluate_without_a_record(self):
        """A menu entry has no active record, so its action's context must not need one.

        `active_id` is legitimate on an action opened from a form button -- the
        button executor puts it in the evaluation context first. A menu does
        not, so the same expression raises before any view is built and the
        entry opens on an error dialog. The two cases are indistinguishable in
        the action record itself; only reachability tells them apart.
        """
        menus = self.env["ir.ui.menu"].search([("action", "!=", False)])
        external_ids = menus.get_external_id()
        menus = menus.filtered(
            lambda m: (external_ids.get(m.id) or "").startswith("project.")
        )
        self.assertTrue(menus, "expected menus from project")
        failures = []
        for menu in menus:
            action = menu.action
            context = getattr(action, "context", None)
            if not context or not isinstance(context, str):
                continue
            try:
                # What the client has: user context only, no active record.
                safe_eval(context, {"uid": self.env.uid, "allowed_company_ids": []})
            except Exception as exc:
                failures.append(
                    f"{external_ids.get(menu.id)} -> {action.xml_id or action.name}: "
                    f"{type(exc).__name__}: {str(exc)[:70]}"
                )
        self.assertFalse(
            failures,
            "menu actions whose context needs an active record:\n  "
            + "\n  ".join(failures),
        )


@tagged("post_install", "-at_install")
class TestRetrospectiveOrdering(TestProjectCommon):
    """Retrospective actions surface the open ones first."""

    def test_retrospective_actions_list_open_items_first(self) -> None:
        """_order sorted on the raw selection keys, putting Done above Open."""
        retro = self.env["project.retrospective"].create(
            {"name": "R", "project_id": self.project_pigs.id}
        )
        Action = self.env["project.retrospective.action"]
        for name, state in (
            ("z-open", "open"),
            ("a-done", "done"),
            ("m-inprog", "in_progress"),
        ):
            Action.create(
                {
                    "name": name,
                    "retrospective_id": retro.id,
                    "owner_id": self.env.uid,
                    "state": state,
                }
            )
        ordered = Action.search([("retrospective_id", "=", retro.id)]).mapped("state")
        self.assertEqual(ordered, ["open", "in_progress", "done"])


@tagged("post_install", "-at_install")
class TestPmModelBehaviour(TestProjectCommon):
    """Behaviour of the PM-layer models: benefits, baselines, risks, gates, phases, roles, history."""

    def test_benefit_review_cron_creates_activity_with_deadline(self) -> None:
        """The benefit-review cron must write ``date_deadline`` on mail.activity
        (the fork's date_deadline→date_end rename is task-only).

        Bug: it wrote ``date_end`` — a field mail.activity does not have — so the
        cron raised ValueError on every run and no reminder was ever created.
        """
        review = fields.Date.context_today(self.env["project.benefit"]) - timedelta(
            days=1
        )
        benefit = self.env["project.benefit"].create(
            {
                "name": "Cut fuel cost",
                "project_id": self.project_pigs.id,
                "accountable_id": self.user_projectmanager.id,
                "review_date": review,
                "state": "tracking",
            }
        )
        self.env["project.benefit"]._cron_check_review_dates()
        activity = self.env["mail.activity"].search(
            [
                ("res_model", "=", "project.benefit"),
                ("res_id", "=", benefit.id),
            ]
        )
        self.assertEqual(len(activity), 1, "Cron must schedule exactly one activity")
        self.assertEqual(activity.date_deadline, review)
        # Idempotent: a second run must not duplicate the activity.
        self.env["project.benefit"]._cron_check_review_dates()
        self.assertEqual(
            self.env["mail.activity"].search_count(
                [
                    ("res_model", "=", "project.benefit"),
                    ("res_id", "=", benefit.id),
                ]
            ),
            1,
            "Cron must be idempotent",
        )

    def test_benefit_cron_does_not_renag_after_completion(self) -> None:
        """Once a reminder is scheduled for a review_date, the cron must not
        re-create it on later runs (even after the user completes it). It
        re-arms only when review_date moves forward."""
        Benefit = self.env["project.benefit"]
        today = fields.Date.context_today(Benefit)
        benefit = Benefit.create(
            {
                "name": "Reduce cost",
                "project_id": self.project_pigs.id,
                "accountable_id": self.user_projectmanager.id,
                "review_date": today - timedelta(days=5),
                "state": "tracking",
            }
        )
        Benefit._cron_check_review_dates()
        acts = self.env["mail.activity"].search(
            [("res_model", "=", "project.benefit"), ("res_id", "=", benefit.id)]
        )
        self.assertEqual(len(acts), 1, "first run schedules one reminder")
        self.assertEqual(benefit.review_reminder_date, benefit.review_date)
        # User completes (deletes) the activity, then the cron runs again.
        acts.unlink()
        Benefit._cron_check_review_dates()
        self.assertEqual(
            self.env["mail.activity"].search_count(
                [("res_model", "=", "project.benefit"), ("res_id", "=", benefit.id)]
            ),
            0,
            "cron must NOT re-nag for the same review_date after completion",
        )
        # Moving review_date forward re-arms the reminder.
        benefit.review_date = today - timedelta(days=1)
        Benefit._cron_check_review_dates()
        self.assertEqual(
            self.env["mail.activity"].search_count(
                [("res_model", "=", "project.benefit"), ("res_id", "=", benefit.id)]
            ),
            1,
            "a new review_date must schedule a fresh reminder",
        )

    def test_duplicate_current_baseline(self) -> None:
        """C2: copying the current baseline must not hit the partial unique index."""
        baseline = self.env["project.baseline"].create(
            {"project_id": self.project_pigs.id, "name": "B1"}
        )
        baseline.action_set_current()
        baseline.flush_recordset()
        copy = baseline.copy()  # must not raise IntegrityError
        copy.flush_recordset()
        self.assertFalse(copy.is_current, "the copy must not also be current")

    def test_baseline_snapshot_uses_planned_start(self) -> None:
        """Baseline snapshots must capture planned_date_begin (scheduled start),
        not date_assign (actual assignment)."""
        project = self.env["project.project"].create({"name": "BaseProj"})
        begin = fields.Datetime.now() - timedelta(days=5)
        task = self.env["project.task"].create(
            {
                "name": "planned",
                "project_id": project.id,
                "planned_date_begin": begin,
                "date_end": begin + timedelta(days=1),
            }
        )
        baseline = self.env["project.baseline"].create(
            {"name": "B1", "project_id": project.id}
        )
        baseline.action_capture_snapshot()
        line = baseline.line_ids.filtered(lambda line: line.task_id == task)
        self.assertEqual(line.planned_start, begin)

    def test_confidential_child_models_not_leaked(self) -> None:
        """S1: a plain project user who is not a follower of a follower-only
        project must not see that project's risks (mirrors the task rule),
        but must still see risks of an employees-visible project."""
        Risk = self.env["project.risk"]
        secret = Risk.create(
            {
                "project_id": self.project_goats.id,  # privacy_visibility='followers'
                "name": "SECRET",
                "probability": "5",
                "impact": "5",
            }
        )
        visible = Risk.create(
            {
                "project_id": self.project_pigs.id,  # privacy_visibility='employees'
                "name": "OPEN",
                "probability": "1",
                "impact": "1",
            }
        )
        as_user = Risk.with_user(self.user_projectuser)
        self.assertNotIn(
            secret,
            as_user.search([("project_id", "=", self.project_goats.id)]),
            "follower-only project's risk must be hidden from non-follower user",
        )
        self.assertIn(
            visible,
            as_user.search([("project_id", "=", self.project_pigs.id)]),
            "employees-visible project's risk must remain readable",
        )

    def test_resolved_risk_excluded_from_counts(self) -> None:
        """H1: a resolved risk no longer counts toward risk_count / health."""
        risk = self.env["project.risk"].create(
            {
                "project_id": self.project_pigs.id,
                "name": "R",
                "probability": "5",
                "impact": "5",
            }
        )
        self.project_pigs.invalidate_recordset(["risk_count"])
        self.assertEqual(self.project_pigs.risk_count, 1)
        risk.state = "resolved"
        self.project_pigs.invalidate_recordset(["risk_count"])
        self.assertEqual(
            self.project_pigs.risk_count,
            0,
            "resolved risks must be excluded from the open-risk count",
        )

    def test_retrospective_carry_forward_idempotent(self) -> None:
        """action_carry_forward run twice must not duplicate carried actions."""
        project = self.env["project.project"].create({"name": "RetroProj"})
        prev = self.env["project.retrospective"].create(
            {"name": "Sprint 1", "project_id": project.id}
        )
        self.env["project.retrospective.action"].create(
            {
                "name": "Fix CI",
                "retrospective_id": prev.id,
                "state": "open",
                "owner_id": self.user_projectuser.id,
            }
        )
        current = self.env["project.retrospective"].create(
            {"name": "Sprint 2", "project_id": project.id, "previous_id": prev.id}
        )
        current.action_carry_forward()
        current.action_carry_forward()
        self.assertEqual(len(current.action_ids), 1, "carry-forward must be idempotent")

    def test_history_duration_uses_completion_not_today(self) -> None:
        """project.history actual duration must key off real completion (last
        task closure), not the snapshot date."""
        start = fields.Date.today() - timedelta(days=100)
        project = self.env["project.project"].create(
            # Both dates: a project carries its scheduling pair or neither
            # (owner-confirmed rule, now enforced on create as well as write).
            {"name": "HistProj", "date_start": start, "date": fields.Date.today()}
        )
        task = self.env["project.task"].create({"name": "T", "project_id": project.id})
        # Completed 90 days after start (10 days before "today").
        task.write({"state": "done"})
        task.date_closed = fields.Datetime.to_datetime(start) + timedelta(days=90)
        hist = self.env["project.history"].create_from_project(project)
        self.assertEqual(
            hist.actual_duration_days,
            90,
            "duration must be start→last-closure (90d), not start→today (100d)",
        )
        self.assertEqual(hist.date_completed, (start + timedelta(days=90)))

    def test_gate_criterion_counts(self) -> None:
        """criteria_met_count / criteria_total_count must reflect the criteria
        and react to a criterion being marked met."""
        gate = self.env["project.gate"].create(
            {"name": "G1", "project_id": self.project_pigs.id}
        )
        c1 = self.env["project.gate.criterion"].create(
            {"gate_id": gate.id, "name": "Budget ok"}
        )
        self.env["project.gate.criterion"].create(
            {"gate_id": gate.id, "name": "Scope ok"}
        )
        self.assertEqual(gate.criteria_total_count, 2)
        self.assertEqual(gate.criteria_met_count, 0)
        c1.met = True
        self.assertEqual(
            gate.criteria_met_count, 1, "met count must react to criterion.met"
        )

    def test_gate_criterion_milestone_cross_project_guard(self) -> None:
        """A gate's trigger milestone must belong to the gate's project."""
        self.project_goats.allow_milestones = True
        other_ms = self.env["project.milestone"].create(
            {"name": "Other", "project_id": self.project_goats.id}
        )
        with self.assertRaises(ValidationError):
            self.env["project.gate"].create(
                {
                    "name": "BadGate",
                    "project_id": self.project_pigs.id,
                    "milestone_id": other_ms.id,
                }
            )

    def test_role_defaults_and_task_assignment(self) -> None:
        """project.role gets a color in range and can be assigned to a task."""
        role = self.env["project.role"].create({"name": "Reviewer"})
        self.assertTrue(1 <= role.color <= 11, "default color must be in [1, 11]")
        self.task_1.role_ids = [(4, role.id)]
        self.assertIn(role, self.task_1.role_ids)
        # copy suffix from the shared mixin.
        self.assertEqual(role.copy().name, "Reviewer (copy)")

    def test_phase_write_company_switch_guard(self) -> None:
        """Switching a phase's company must raise while a project of a different
        company is still assigned to it."""
        company_a = self.env["res.company"].create({"name": "Co A"})
        company_b = self.env["res.company"].create({"name": "Co B"})
        phase = self.env["project.phase"].create(
            {"name": "Planning", "company_id": company_a.id}
        )
        self.env["project.project"].create(
            {
                "name": "In phase",
                "phase_id": phase.id,
                "company_id": company_a.id,
            }
        )
        with self.assertRaises(UserError):
            phase.company_id = company_b.id
        # No conflicting project → the switch is allowed.
        empty_phase = self.env["project.phase"].create(
            {"name": "Empty", "company_id": company_a.id}
        )
        empty_phase.company_id = company_b.id
        self.assertEqual(empty_phase.company_id, company_b)

    def test_phase_archive_cascades_to_projects(self) -> None:
        """Archiving a phase archives every project assigned to it."""
        phase = self.env["project.phase"].create({"name": "Closing"})
        project = self.env["project.project"].create(
            {"name": "Cascade", "phase_id": phase.id}
        )
        self.assertTrue(project.active)
        phase.active = False
        self.assertFalse(
            project.active, "archiving the phase must archive its projects"
        )
