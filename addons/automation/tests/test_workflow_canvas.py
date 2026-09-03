from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user


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
