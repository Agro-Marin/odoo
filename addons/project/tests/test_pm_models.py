"""Coverage for previously-untested fork PM models + the 1.8 DB constraints.

Before this file, project.sprint / project.baseline / project.gate /
project.risk / project.retrospective had zero behavioural tests. These lock in
the invariants (one current baseline, one active sprint, cross-project gate
milestone, retrospective non-cyclic chain) and the core computes.
"""

from datetime import timedelta

from psycopg import IntegrityError

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

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
        Baseline.create({
            "name": "B1", "project_id": self.project_pigs.id, "is_current": True,
        })
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                Baseline.create({
                    "name": "B2",
                    "project_id": self.project_pigs.id,
                    "is_current": True,
                })
                self.env.flush_all()

    def test_baseline_action_set_current_unsets_prior(self) -> None:
        Baseline = self.env["project.baseline"]
        b1 = Baseline.create({
            "name": "B1", "project_id": self.project_pigs.id, "is_current": True,
        })
        b2 = Baseline.create({"name": "B2", "project_id": self.project_pigs.id})
        b2.action_set_current()
        self.assertFalse(b1.is_current)
        self.assertTrue(b2.is_current)

    def test_baseline_snapshot_fidelity_and_double_capture(self) -> None:
        task = self.env["project.task"].create({
            "name": "Snap me",
            "project_id": self.project_goats.id,
            "date_end": fields.Datetime.now(),
            "step_id": self.project_goats.workflow_step_ids[0].id,
        })
        baseline = self.env["project.baseline"].create({
            "name": "Snapshot", "project_id": self.project_goats.id,
        })
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
        return self.env["project.sprint"].create({
            "name": name,
            "project_id": self.project_pigs.id,
            "date_start": self.today,
            "date_end": self.today + timedelta(days=14),
            "state": state,
        })

    def test_sprint_single_active_db_constraint(self) -> None:
        self._make_sprint("S1", state="active")
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
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
        open_task = self.env["project.task"].create({
            "name": "Open", "project_id": self.project_pigs.id, "state": "in_progress",
        })
        done_task = self.env["project.task"].create({
            "name": "Done", "project_id": self.project_pigs.id, "state": "done",
        })
        sprint.task_ids = open_task + done_task
        self.assertEqual(open_task.sprint_id, sprint)
        sprint.action_close()
        self.assertEqual(sprint.state, "closed")
        self.assertFalse(open_task.sprint_id, "open task is released on close")
        self.assertEqual(done_task.sprint_id, sprint, "closed task stays for history")

    def test_sprint_task_metrics(self) -> None:
        sprint = self._make_sprint("S1")
        t_open = self.env["project.task"].create({
            "name": "O", "project_id": self.project_pigs.id,
            "state": "in_progress", "planned_hours": 4.0,
        })
        t_done = self.env["project.task"].create({
            "name": "D", "project_id": self.project_pigs.id,
            "state": "done", "planned_hours": 6.0,
        })
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
        foreign_milestone = self.env["project.milestone"].create({
            "name": "Foreign", "project_id": self.project_goats.id,
        })
        with self.assertRaises(ValidationError):
            self.env["project.gate"].create({
                "name": "Gate",
                "project_id": self.project_pigs.id,
                "milestone_id": foreign_milestone.id,
            })

    # ----- project.retrospective -------------------------------------------
    def test_retrospective_no_self_cycle(self) -> None:
        retro = self.env["project.retrospective"].create({
            "name": "R1", "project_id": self.project_pigs.id,
        })
        with self.assertRaises(ValidationError):
            retro.previous_id = retro

    def test_retrospective_carry_forward(self) -> None:
        r1 = self.env["project.retrospective"].create({
            "name": "R1", "project_id": self.project_pigs.id,
        })
        Action = self.env["project.retrospective.action"]
        owner = self.user_projectuser.id
        Action.create({
            "name": "Open action", "retrospective_id": r1.id,
            "state": "open", "owner_id": owner,
        })
        Action.create({
            "name": "Done action", "retrospective_id": r1.id,
            "state": "done", "owner_id": owner,
        })
        r2 = self.env["project.retrospective"].create({
            "name": "R2", "project_id": self.project_pigs.id, "previous_id": r1.id,
        })
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
        triage = self.env["project.triage"].create({
            "name": "Today", "user_id": self.user_projectuser.id,
        })
        self.assertEqual(step.copy().name, "Backlog (copy)")
        self.assertEqual(phase.copy().name, "Planning (copy)")
        self.assertEqual(role.copy().name, "Reviewer (copy)")
        self.assertEqual(triage.copy().name, "Today (copy)")

    # ----- project.risk -----------------------------------------------------
    def test_risk_score_level_boundaries(self) -> None:
        Risk = self.env["project.risk"]
        cases = [
            ("1", "4", 4, "low"),      # 4  -> low  (below 5)
            ("1", "5", 5, "medium"),   # 5  -> medium (boundary)
            ("3", "3", 9, "medium"),   # 9  -> medium (below 10)
            ("2", "5", 10, "high"),    # 10 -> high (boundary)
            ("3", "5", 15, "high"),    # 15 -> high (below 16)
            ("4", "4", 16, "critical"),  # 16 -> critical (boundary)
        ]
        for prob, impact, score, level in cases:
            risk = Risk.create({
                "name": f"R{score}",
                "project_id": self.project_pigs.id,
                "probability": prob,
                "impact": impact,
            })
            self.assertEqual(risk.risk_score, score)
            self.assertEqual(
                risk.risk_level, level, f"prob={prob} impact={impact} score={score}"
            )
