from psycopg.errors import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools import mute_logger


class TestWorkflowCanvasState(TransactionCase):
    def setUp(self):
        super().setUp()
        self.model_partner = self.env["ir.model"]._get("res.partner")
        self.automation = self.env["automation.rule"].create(
            {
                "name": "Canvas State",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
            }
        )
        self.first, self.second, self.third = self.env["ir.actions.server"].create(
            [
                {
                    "name": name,
                    "model_id": self.model_partner.id,
                    "state": "code",
                    "code": "pass",
                    "automation_rule_id": self.automation.id,
                    "usage": "automation",
                }
                for name in ("first", "second", "third")
            ]
        )

    def _link(self, source, target, condition="on_success"):
        return self.env["workflow.edge"].create(
            {
                "source_node_id": source.id,
                "target_node_id": target.id,
                "condition": condition,
            }
        )


class TestNodeSize(TestWorkflowCanvasState):
    def test_zero_is_the_unset_size(self):
        self.first.write({"pos_width": 0, "pos_height": 0})
        self.assertFalse(self.first.pos_width or self.first.pos_height)

    def test_a_size_inside_the_bounds_is_stored(self):
        self.first.write({"pos_width": 300, "pos_height": 150})
        self.assertEqual((self.first.pos_width, self.first.pos_height), (300, 150))

    def test_a_width_under_the_minimum_is_refused(self):
        with self.assertRaises(ValidationError):
            self.first.pos_width = 40

    def test_a_width_over_the_maximum_is_refused(self):
        with self.assertRaises(ValidationError):
            self.first.pos_width = 5000

    def test_a_height_under_the_minimum_is_refused(self):
        with self.assertRaises(ValidationError):
            self.first.pos_height = 10

    def test_a_height_over_the_maximum_is_refused(self):
        with self.assertRaises(ValidationError):
            self.first.pos_height = 900

    def test_the_payload_carries_the_bounds_and_resolves_the_default(self):
        self.first.write({"pos_width": 320, "pos_height": 200})

        payload = self.automation.get_workflow_graph()
        sizes = {
            node["id"]: (node["width"], node["height"]) for node in payload["nodes"]
        }
        bounds = payload["node_size"]

        self.assertEqual(sizes[self.first.id], (320, 200))
        self.assertEqual(
            sizes[self.second.id],
            (bounds["default"]["width"], bounds["default"]["height"]),
        )
        self.assertLess(bounds["min"]["width"], bounds["default"]["width"])
        self.assertGreater(bounds["max"]["width"], bounds["default"]["width"])
        self.assertGreater(bounds["header_height"], 0)

    def test_every_bound_the_payload_states_is_the_one_enforced(self):
        bounds = self.automation.get_workflow_graph()["node_size"]

        for axis, field in (("width", "pos_width"), ("height", "pos_height")):
            self.first.write({field: bounds["min"][axis]})
            self.first.write({field: bounds["max"][axis]})
            with self.assertRaises(ValidationError):
                self.first.write({field: bounds["min"][axis] - 1})
            with self.assertRaises(ValidationError):
                self.first.write({field: bounds["max"][axis] + 1})


class TestStepRemoval(TestWorkflowCanvasState):
    """The canvas offers to remove a step, so the payload has to say which.

    `automation.runtime.line.action_id` is `ondelete="restrict"`, and nothing on
    the step itself records that a run once reached it, so the client cannot
    work this out for itself.
    """

    def _record_a_run_over(self, action):
        runtime = self.env["automation.runtime"].create(
            {
                "automation_id": self.automation.id,
                "res_model": "res.partner",
                "res_id": self.env.user.partner_id.id,
            }
        )
        return self.env["automation.runtime.line"].create(
            {
                "runtime_id": runtime.id,
                "action_id": action.id,
                "name": action.name,
            }
        )

    def test_a_step_no_run_reached_is_offered_for_removal(self):
        deletable = {
            node["id"]: node["deletable"]
            for node in self.automation.get_workflow_graph()["nodes"]
        }

        self.assertEqual(
            deletable,
            {self.first.id: True, self.second.id: True, self.third.id: True},
        )

    def test_a_step_a_run_reached_is_withheld(self):
        self._record_a_run_over(self.second)

        deletable = {
            node["id"]: node["deletable"]
            for node in self.automation.get_workflow_graph()["nodes"]
        }

        self.assertEqual(
            deletable,
            {self.first.id: True, self.second.id: False, self.third.id: True},
        )

    def test_the_withheld_step_is_the_one_that_cannot_be_unlinked(self):
        """The flag's whole reason, measured rather than asserted."""
        self._record_a_run_over(self.second)

        with self.assertRaises(IntegrityError), mute_logger("odoo.db.cursor"):
            with self.env.cr.savepoint():
                self.second.unlink()

    def test_removing_a_step_takes_the_edges_that_touch_it(self):
        self._link(self.first, self.second)
        self._link(self.second, self.third)
        edge_ids = self.automation.edge_ids.ids

        self.first.unlink()

        self.assertEqual(len(self.automation.edge_ids), 1)
        self.assertTrue(self.env["workflow.edge"].browse(edge_ids[1]).exists())

    def test_a_run_of_another_company_still_withholds_the_step(self):
        """The flag answers for Postgres, not for the reader's companies.

        `automation.runtime.line` carries a global multi-company rule, so a
        reader outside the run's company sees no line for it. Read without
        `sudo` the payload offered this step for removal and the constraint then
        refused it, which is the one shape the flag exists to prevent.
        """
        elsewhere = self.env["res.company"].create({"name": "Elsewhere Co"})
        runtime = self.env["automation.runtime"].create(
            {
                "automation_id": self.automation.id,
                "company_id": elsewhere.id,
                "res_model": "res.partner",
                "res_id": self.env.user.partner_id.id,
            }
        )
        self.env["automation.runtime.line"].create(
            {
                "runtime_id": runtime.id,
                "action_id": self.second.id,
                "name": self.second.name,
            }
        )
        reader = new_test_user(
            self.env, login="canvas_outsider", groups="base.group_system"
        )
        self.assertNotIn(elsewhere, reader.company_ids)
        self.assertFalse(
            self.env["automation.runtime.line"]
            .with_user(reader)
            .search([("action_id", "=", self.second.id)]),
            "the premise: the reader cannot see the line that holds the step",
        )

        deletable = {
            node["id"]: node["deletable"]
            for node in self.automation.with_user(reader).get_workflow_graph()["nodes"]
        }

        self.assertFalse(deletable[self.second.id])
        self.assertTrue(deletable[self.first.id])
        self.assertEqual(
            self.env["automation.runtime.line"]._fields["action_id"].ondelete,
            "restrict",
        )

    def test_the_payload_says_nothing_about_another_automations_runs(self):
        other = self.env["automation.rule"].create(
            {
                "name": "Elsewhere",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
            }
        )
        elsewhere = self.env["ir.actions.server"].create(
            {
                "name": "elsewhere",
                "model_id": self.model_partner.id,
                "state": "code",
                "code": "pass",
                "automation_rule_id": other.id,
                "usage": "automation",
            }
        )
        runtime = self.env["automation.runtime"].create(
            {
                "automation_id": other.id,
                "res_model": "res.partner",
                "res_id": self.env.user.partner_id.id,
            }
        )
        self.env["automation.runtime.line"].create(
            {
                "runtime_id": runtime.id,
                "action_id": elsewhere.id,
                "name": elsewhere.name,
            }
        )

        deletable = {
            node["id"]: node["deletable"]
            for node in self.automation.get_workflow_graph()["nodes"]
        }

        self.assertTrue(all(deletable.values()))
        self.assertNotIn(elsewhere.id, deletable)


class TestStepDetail(TestWorkflowCanvasState):
    """A typed step carries the parameter that gives its type meaning.

    Without these the canvas draws "Wait" with no duration, "Approval" with
    nobody named and "Subflow" without saying which automation it runs.
    """

    def _nodes(self):
        return {
            node["id"]: node for node in self.automation.get_workflow_graph()["nodes"]
        }

    def test_a_wait_step_carries_its_duration(self):
        self.first.write({"node_type": "wait", "wait_delay": 36, "wait_unit": "hours"})

        node = self._nodes()[self.first.id]

        self.assertEqual((node["wait_delay"], node["wait_unit"]), (36, "hours"))

    def test_an_approval_step_carries_its_approvers(self):
        approver = new_test_user(self.env, login="canvas_approver")
        self.first.write(
            {
                "node_type": "approval",
                "approval_user_ids": [(6, 0, approver.ids)],
                "approval_note": "Sign it",
            }
        )

        self.assertEqual(
            self._nodes()[self.first.id]["approver_names"],
            approver.display_name,
        )

    def test_a_subflow_step_names_the_automation_it_runs(self):
        target = self.env["automation.rule"].create(
            {
                "name": "Nightly sweep",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
            }
        )
        self.first.write({"node_type": "subflow", "subflow_automation_id": target.id})

        self.assertEqual(self._nodes()[self.first.id]["subflow_name"], "Nightly sweep")

    def test_a_plain_action_step_names_no_approver_and_no_subflow(self):
        node = self._nodes()[self.second.id]

        self.assertEqual(node["approver_names"], "")
        self.assertEqual(node["subflow_name"], "")


class TestCanvasViewport(TestWorkflowCanvasState):
    def setUp(self):
        super().setUp()
        self.reader = new_test_user(
            self.env, login="canvas_reader", groups="base.group_system"
        )
        self.other = new_test_user(
            self.env, login="canvas_other", groups="base.group_system"
        )
        self.Viewport = self.env["automation.canvas.viewport"]

    def test_a_viewport_is_stored_for_the_caller(self):
        self.automation.with_user(self.reader).set_workflow_viewport(-120.0, 60.0, 1.5)

        stored = self.Viewport.search([("automation_rule_id", "=", self.automation.id)])
        self.assertEqual(stored.user_id, self.reader)
        self.assertEqual(
            (stored.pos_x, stored.pos_y, stored.scale), (-120.0, 60.0, 1.5)
        )

    def test_saving_twice_updates_the_one_row(self):
        automation = self.automation.with_user(self.reader)
        automation.set_workflow_viewport(-120.0, 60.0, 1.5)
        automation.set_workflow_viewport(-10.0, 20.0, 0.5)

        stored = self.Viewport.search([("automation_rule_id", "=", self.automation.id)])
        self.assertEqual(len(stored), 1)
        self.assertEqual((stored.pos_x, stored.pos_y, stored.scale), (-10.0, 20.0, 0.5))

    def test_two_readers_keep_two_viewports(self):
        self.automation.with_user(self.reader).set_workflow_viewport(-120.0, 60.0, 1.5)
        self.automation.with_user(self.other).set_workflow_viewport(0.0, 0.0, 1.0)

        self.assertEqual(
            len(
                self.Viewport.search([("automation_rule_id", "=", self.automation.id)])
            ),
            2,
        )

    def test_a_reader_sees_only_their_own(self):
        self.automation.with_user(self.reader).set_workflow_viewport(-120.0, 60.0, 1.5)
        self.automation.with_user(self.other).set_workflow_viewport(7.0, 8.0, 1.0)

        as_reader = self.Viewport.with_user(self.reader).search([])
        self.assertEqual(as_reader.user_id, self.reader)
        self.assertEqual((as_reader.pos_x, as_reader.pos_y), (-120.0, 60.0))

    def test_the_payload_returns_the_callers_own_viewport(self):
        self.automation.with_user(self.reader).set_workflow_viewport(-120.0, 60.0, 1.5)

        as_reader = self.automation.with_user(self.reader).get_workflow_graph()
        as_other = self.automation.with_user(self.other).get_workflow_graph()

        self.assertEqual(as_reader["viewport"], {"x": -120.0, "y": 60.0, "scale": 1.5})
        self.assertIsNone(as_other["viewport"])

    def test_a_zoom_outside_what_the_canvas_draws_is_refused(self):
        for scale in (0.0, 0.01, 3.0):
            with self.subTest(scale=scale), self.assertRaises(ValidationError):
                self.Viewport.create(
                    {
                        "user_id": self.reader.id,
                        "automation_rule_id": self.automation.id,
                        "scale": scale,
                    }
                )

    def test_deleting_the_automation_takes_its_viewports_with_it(self):
        self.automation.with_user(self.reader).set_workflow_viewport(-1.0, -2.0, 1.0)
        rule_id = self.automation.id

        self.automation.unlink()

        self.assertFalse(self.Viewport.search([("automation_rule_id", "=", rule_id)]))


class TestWorkflowCounts(TestWorkflowCanvasState):
    def test_the_counts_follow_the_graph(self):
        self.assertEqual(self.automation.step_count, 3)
        self.assertEqual(self.automation.edge_count, 0)

        self._link(self.first, self.second)
        self._link(self.second, self.third)
        self.assertEqual(self.automation.edge_count, 2)

        self.third.unlink()
        self.assertEqual(self.automation.step_count, 2)
        self.assertEqual(self.automation.edge_count, 1)

    def test_the_counts_are_stored_and_searchable(self):
        self._link(self.first, self.second)
        self.automation.flush_recordset()

        self.assertIn(
            self.automation,
            self.env["automation.rule"].search([("step_count", "=", 3)]),
        )
        self.assertIn(
            self.automation,
            self.env["automation.rule"].search([("edge_count", "=", 1)]),
        )

    def test_an_unsaved_automation_counts_the_steps_in_the_form(self):
        draft = self.env["automation.rule"].new(
            {
                "name": "Draft",
                "model_id": self.model_partner.id,
                "trigger": "on_hand",
                "action_server_ids": [
                    (0, 0, {"name": "one", "state": "code", "code": "pass"}),
                    (0, 0, {"name": "two", "state": "code", "code": "pass"}),
                ],
            }
        )

        self.assertEqual(draft.step_count, 2)
        self.assertEqual(draft.edge_count, 0)
