from urllib.parse import urlencode

from odoo import Command
from odoo.tests import HttpCase, tagged


def _urlencode_kwargs(**kwargs):
    return urlencode(kwargs)


@tagged("post_install_l10n", "post_install", "-at_install")
class AutomationRuleTestUi(HttpCase):
    def _neutralize_preexisting_automations(self, neutralize_action=True):
        self.env["automation.rule"].with_context(active_test=False).search([]).write(
            {"active": False}
        )
        if neutralize_action:
            context = self.env["ir.actions.actions"]._eval_action_context(
                self.env.ref("automation.automation_act").context
            )
            del context["search_default_inactive"]
            self.env.ref("automation.automation_act").context = str(context)

    def test_01_automation_tour(self):
        self._neutralize_preexisting_automations()
        self.start_tour(
            "/odoo/action-automation.automation_act?debug=tests",
            "test_automation",
            login="admin",
        )
        automation = self.env["automation.rule"].search([])
        self.assertEqual(automation.model_id.model, "res.partner")
        self.assertEqual(automation.trigger, "on_create_or_write")
        self.assertEqual(
            automation.action_server_ids.state, "object_write"
        )  # only one action
        self.assertEqual(automation.action_server_ids.model_name, "res.partner")
        self.assertEqual(automation.action_server_ids.update_field_id.name, "function")
        self.assertEqual(automation.action_server_ids.value, "Test")

    def test_automation_on_tag_added(self):
        self._neutralize_preexisting_automations()
        self.env["test_automation.tag"].create({"name": "test"})
        self.start_tour(
            "/odoo/action-automation.automation_act?debug=tests",
            "test_automation_on_tag_added",
            login="admin",
        )

    def test_open_automation_from_grouped_kanban(self):
        self._neutralize_preexisting_automations()

        test_view = self.env["ir.ui.view"].create(
            {
                "name": "test_view",
                "model": "test_automation.project",
                "type": "kanban",
                "arch": """
                    <kanban default_group_by="tag_ids">
                        <templates>
                            <t t-name="card">
                                <field name="name" />
                            </t>
                        </templates>
                    </kanban>
                """,
            }
        )
        test_action = self.env["ir.actions.act_window"].create(
            {
                "name": "test action",
                "res_model": "test_automation.project",
                "view_ids": [
                    Command.create({"view_id": test_view.id, "view_mode": "kanban"})
                ],
            }
        )
        tag = self.env["test_automation.tag"].create({"name": "test tag"})
        self.env["test_automation.project"].create(
            {"name": "test", "tag_ids": [Command.link(tag.id)]}
        )

        self.start_tour(
            f"/odoo/action-{test_action.id}?debug=0",
            "test_open_automation_from_grouped_kanban",
            login="admin",
        )
        base_auto = self.env["automation.rule"].search([])
        self.assertEqual(base_auto.name, "From Tour")
        self.assertEqual(base_auto.model_name, "test_automation.project")
        self.assertEqual(base_auto.trigger_field_ids.name, "tag_ids")
        self.assertEqual(base_auto.trigger, "on_tag_set")
        self.assertEqual(base_auto.trg_field_ref_model_name, "test_automation.tag")
        self.assertEqual(base_auto.trg_field_ref, tag.id)

    def test_kanban_automation_view_stage_trigger(self):
        self._neutralize_preexisting_automations()

        project_model = self.env.ref("test_automation.model_test_automation_project")
        stage_field = self.env["ir.model.fields"].search(
            [
                ("model_id", "=", project_model.id),
                ("name", "=", "stage_id"),
            ]
        )
        test_stage = self.env["test_automation.stage"].create({"name": "Stage value"})

        automation = self.env["automation.rule"].create(
            {
                "name": "Test Stage",
                "trigger": "on_stage_set",
                "model_id": project_model.id,
                "trigger_field_ids": [stage_field.id],
                "trg_field_ref": test_stage,
            }
        )

        action = {
            "name": "Set Active To False",
            "automation_rule_id": automation.id,
            "state": "object_write",
            "update_path": "user_ids.active",
            "value": False,
            "model_id": project_model.id,
        }
        automation.write({"action_server_ids": [Command.create(action)]})

        self.start_tour(
            "/odoo/action-automation.automation_act",
            "test_kanban_automation_view_stage_trigger",
            login="admin",
        )

    def test_kanban_automation_view_time_trigger(self):
        self._neutralize_preexisting_automations()
        model = self.env["ir.model"]._get("automation.lead.test")

        date_field = self.env["ir.model.fields"].search(
            [
                ("model_id", "=", model.id),
                ("name", "=", "date_automation_last"),
            ]
        )

        self.env["automation.rule"].create(
            {
                "name": "Test Date",
                "trigger": "on_time",
                "model_id": model.id,
                "trg_date_range": 1,
                "trg_date_range_type": "hour",
                "trg_date_id": date_field.id,
            }
        )

        self.start_tour(
            "/odoo/action-automation.automation_act",
            "test_kanban_automation_view_time_trigger",
            login="admin",
        )

    def test_kanban_automation_view_time_updated_trigger(self):
        self._neutralize_preexisting_automations()
        model = self.env.ref("base.model_res_partner")

        self.env["automation.rule"].create(
            {
                "name": "Test Date",
                "trigger": "on_time_updated",
                "model_id": model.id,
                "trg_date_range": 1,
                "trg_date_range_type": "hour",
            }
        )

        self.start_tour(
            "/odoo/action-automation.automation_act",
            "test_kanban_automation_view_time_updated_trigger",
            login="admin",
        )

    def test_kanban_automation_view_create_action(self):
        self._neutralize_preexisting_automations()
        model = self.env.ref("base.model_res_partner")

        automation = self.env["automation.rule"].create(
            {
                "name": "Test",
                "trigger": "on_create_or_write",
                "model_id": model.id,
            }
        )

        action = {
            "name": "Create Contact with name NameX",
            "automation_rule_id": automation.id,
            "state": "object_create",
            "value": "NameX",
            "model_id": model.id,
        }

        automation.write({"action_server_ids": [Command.create(action)]})

        self.start_tour(
            "/odoo/action-automation.automation_act",
            "test_kanban_automation_view_create_action",
            login="admin",
        )

    def test_resize_kanban(self):
        self._neutralize_preexisting_automations()
        model = self.env.ref("base.model_res_partner")

        automation = self.env["automation.rule"].create(
            {
                "name": "Test",
                "trigger": "on_create_or_write",
                "model_id": model.id,
            }
        )

        action = {
            "name": "Set Active To False",
            "automation_rule_id": automation.id,
            "state": "object_write",
            "update_path": "active",
            "value": False,
            "model_id": model.id,
        }
        automation.write(
            {"action_server_ids": [Command.create(action) for i in range(3)]}
        )

        self.start_tour(
            "/odoo/action-automation.automation_act",
            "test_resize_kanban",
            login="admin",
        )

    def test_form_view(self):
        model = self.env.ref("base.model_res_partner")
        automation = self.env["automation.rule"].create(
            {
                "name": "Test",
                "trigger": "on_create_or_write",
                "model_id": model.id,
            }
        )
        action = {
            "name": "Update Active",
            "automation_rule_id": automation.id,
            "state": "object_write",
            "update_path": "active",
            "update_boolean_value": "false",
            "model_id": model.id,
        }
        automation.write(
            {
                "action_server_ids": [
                    Command.create(
                        dict(action, name=action["name"] + f" {i}", sequence=i)
                    )
                    for i in range(3)
                ]
            }
        )
        self.assertEqual(
            automation.action_server_ids.mapped("name"),
            ["Update Active 0", "Update Active 1", "Update Active 2"],
        )

        onchange_link_passes = 0
        origin_link_onchange = type(self.env["ir.actions.server"]).onchange

        def _onchange_base_auto_link(self_model, *args):
            nonlocal onchange_link_passes
            onchange_link_passes += 1
            res = origin_link_onchange(self_model, *args)
            if onchange_link_passes == 1:
                default_keys = {
                    k: v
                    for k, v in self_model.env.context.items()
                    if k.startswith("default_")
                }
                self.assertEqual(
                    default_keys,
                    {"default_model_id": model.id, "default_usage": "automation"},
                )
            if onchange_link_passes == 2:
                self.assertEqual(res["value"]["name"], "Add Followers")

            return res

        self.patch(
            type(self.env["ir.actions.server"]), "onchange", _onchange_base_auto_link
        )

        self.start_tour(
            (f"/odoo/action-automation.automation_act/{automation.id}?debug=0"),
            "test_form_view_resequence_actions",
            login="admin",
        )
        self.assertEqual(onchange_link_passes, 2)
        self.assertEqual(
            automation.action_server_ids.mapped("name"),
            ["Update Active 2", "Update Active 0", "Update Active 1"],
        )

    def test_workflow_canvas(self):
        """Drive the JointJS canvas in a real browser.

        This is the only end-to-end exercise of the vendored bundle: that
        `import("joint")` resolves through the import map, that
        `get_workflow_graph` feeds it, that the auto-layout runs, and that the
        classes the stylesheet declares are the ones the nodes carry. A HOOT
        test can reach none of that.
        """
        model = self.env["ir.model"]._get("res.partner")
        rule = self.env["automation.rule"].create(
            {
                "name": "Canvas Tour",
                "model_id": model.id,
                "trigger": "on_hand",
            }
        )
        actions = self.env["ir.actions.server"].create(
            [
                {
                    "name": name,
                    "model_id": model.id,
                    "state": "code",
                    "code": "pass",
                    "automation_rule_id": rule.id,
                    "usage": "automation",
                }
                for name in ("first", "second", "handler")
            ]
        )
        first, second, handler = actions
        self.env["workflow.edge"].create(
            [
                {"source_node_id": first.id, "target_node_id": second.id},
                {
                    "source_node_id": first.id,
                    "target_node_id": handler.id,
                    "condition": "on_error",
                },
            ]
        )
        self.assertFalse(
            any(actions.mapped("pos_x")) or any(actions.mapped("pos_y")),
            "precondition: nothing is placed before the canvas has been opened",
        )

        self.start_tour(
            f"/odoo/action-automation.automation_act/{rule.id}",
            "test_workflow_canvas",
            login="admin",
        )

        # The canvas laid the graph out and wrote the coordinates back through
        # the plain ORM. This is the only assertion in the suite that the write
        # side of the canvas reaches the database at all.
        actions.invalidate_recordset(["pos_x", "pos_y"])
        self.assertTrue(
            any(actions.mapped("pos_x")) or any(actions.mapped("pos_y")),
            "opening the canvas must persist the layout it computed",
        )

    def test_workflow_canvas_edit(self):
        """Remove a connection by clicking it on the canvas.

        The destructive path, and the one with no server-side API of its own:
        the canvas unlinks a `workflow.edge` through the plain ORM, so this is
        also the proof that the write side is subject to the ordinary access
        rules rather than a bespoke endpoint.
        """
        model = self.env["ir.model"]._get("res.partner")
        rule = self.env["automation.rule"].create(
            {"name": "Canvas Edit", "model_id": model.id, "trigger": "on_hand"}
        )
        first, second, third = self.env["ir.actions.server"].create(
            [
                {
                    "name": name,
                    "model_id": model.id,
                    "state": "code",
                    "code": "pass",
                    "automation_rule_id": rule.id,
                    "usage": "automation",
                }
                for name in ("first", "second", "third")
            ]
        )
        self.env["workflow.edge"].create(
            [
                {"source_node_id": first.id, "target_node_id": second.id},
                {"source_node_id": second.id, "target_node_id": third.id},
            ]
        )
        self.assertEqual(len(rule.edge_ids), 2)

        self.start_tour(
            f"/odoo/action-automation.automation_act/{rule.id}",
            "test_workflow_canvas_edit",
            login="admin",
        )

        rule.invalidate_recordset(["edge_ids"])
        self.assertEqual(
            len(rule.edge_ids),
            1,
            "clicking Remove must delete the edge server-side",
        )

    def test_workflow_canvas_drag(self):
        """Drag a step and check the move reached the database.

        Auto-layout already proves the *write* works; this proves the
        `element:pointerup` handler behind a user's drag fires at all.
        """
        model = self.env["ir.model"]._get("res.partner")
        rule = self.env["automation.rule"].create(
            {"name": "Canvas Drag", "model_id": model.id, "trigger": "on_hand"}
        )
        first, second = self.env["ir.actions.server"].create(
            [
                {
                    "name": name,
                    "model_id": model.id,
                    "state": "code",
                    "code": "pass",
                    "automation_rule_id": rule.id,
                    "usage": "automation",
                    "pos_x": pos_x,
                    "pos_y": 40,
                }
                for name, pos_x in (("first", 40), ("second", 320))
            ]
        )
        self.env["workflow.edge"].create(
            {"source_node_id": first.id, "target_node_id": second.id}
        )
        seeded = (first.pos_x, first.pos_y)

        self.start_tour(
            f"/odoo/action-automation.automation_act/{rule.id}",
            "test_workflow_canvas_drag",
            login="admin",
        )

        first.invalidate_recordset(["pos_x", "pos_y"])
        self.assertNotEqual(
            (first.pos_x, first.pos_y),
            seeded,
            "dragging a step must persist its new position",
        )

    def test_workflow_canvas_connect(self):
        """Create a connection by dragging between two steps.

        The last untested interaction, and the one with the most moving parts:
        a JointJS magnet, `validateConnection`, an ORM create the server may
        refuse, and a reload.
        """
        model = self.env["ir.model"]._get("res.partner")
        rule = self.env["automation.rule"].create(
            {"name": "Canvas Connect", "model_id": model.id, "trigger": "on_hand"}
        )
        first, second, third = self.env["ir.actions.server"].create(
            [
                {
                    "name": name,
                    "model_id": model.id,
                    "state": "code",
                    "code": "pass",
                    "automation_rule_id": rule.id,
                    "usage": "automation",
                    "pos_x": pos_x,
                    "pos_y": 60,
                }
                for name, pos_x in (("first", 40), ("second", 300), ("third", 560))
            ]
        )
        self.env["workflow.edge"].create(
            {"source_node_id": first.id, "target_node_id": second.id}
        )
        self.assertEqual(len(rule.edge_ids), 1)

        self.start_tour(
            f"/odoo/action-automation.automation_act/{rule.id}",
            "test_workflow_canvas_connect",
            login="admin",
        )

        rule.invalidate_recordset(["edge_ids"])
        self.assertEqual(
            len(rule.edge_ids),
            2,
            "dragging between two steps must create an edge",
        )
        self.assertEqual(
            rule.edge_ids.filtered(
                lambda edge: (
                    edge.source_node_id == third and edge.target_node_id == first
                )
            ).condition,
            "on_success",
            "a dragged edge defaults to on_success like a typed one",
        )

    def test_form_view_model_id(self):
        self.start_tour(
            ("/odoo/action-automation.automation_act/new?view_type=form&debug=0"),
            "test_form_view_model_id",
            login="admin",
        )

    def test_form_view_custom_reference_field(self):
        self.env["test_automation.stage"].create({"name": "test stage"})
        self.env["test_automation.tag"].create({"name": "test tag"})
        self.start_tour(
            ("/odoo/action-automation.automation_act/new?view_type=form&debug=0"),
            "test_form_view_custom_reference_field",
            login="admin",
        )

    def test_form_view_mail_triggers(self):
        self.start_tour(
            ("/odoo/action-automation.automation_act/new?view_type=form&debug=0"),
            "test_form_view_mail_triggers",
            login="admin",
        )

    def test_on_change_rule_creation(self):
        """test on_change rule creation from the UI"""
        self.start_tour(
            "/odoo/action-automation.automation_act",
            "automation.on_change_rule_creation",
            login="admin",
        )

        rule = self.env["automation.rule"].search(
            [], order="create_date desc", limit=1
        )[0]
        view_model = self.env["ir.model"]._get("ir.ui.view")
        active_field = self.env["ir.model.fields"].search(
            [
                ("name", "=", "active"),
                ("model", "=", "ir.ui.view"),
            ]
        )[0]
        self.assertEqual(rule.name, "Test rule")
        self.assertEqual(rule.model_id, view_model)
        self.assertEqual(rule.trigger, "on_change")
        self.assertEqual(len(rule.on_change_field_ids), 1)
        self.assertEqual(rule.on_change_field_ids[0], active_field)
