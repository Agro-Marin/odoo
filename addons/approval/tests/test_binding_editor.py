import datetime

from odoo import fields
from odoo.fields import Command
from odoo.tests import common, tagged


@tagged("post_install", "-at_install")
class TestApprovalBindingEditor(common.TransactionCase):
    """What Studio's editor asks the engine when an approval step is added to a button."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Binding = cls.env["approval.binding"]
        cls.Step = cls.env["approval.category.step"]
        cls.first, cls.second, cls.delegate = (
            cls.env["res.users"].create(
                {"name": login, "login": login, "email": f"{login}@test.com"}
            )
            for login in ("editor_first", "editor_second", "editor_delegate")
        )

    def tearDown(self):
        self.Binding._unregister_hook()
        super().tearDown()

    def _add_step(self, method="action_archive", action_id=False):
        return self.Step.browse(
            self.Binding.create_step_for_button("res.partner", method, action_id)
        )

    def test_the_first_step_on_a_button_binds_the_button_as_studio_did(self):
        step = self._add_step()
        binding = self.Binding.search(
            [("model_name", "=", "res.partner"), ("method", "=", "action_archive")]
        )
        self.assertEqual(
            (binding.mode, binding.approve_on_invoke, binding.run_on_approval),
            ("request", True, False),
        )
        self.assertEqual(step.category_id, binding.category_id)
        self.assertEqual(step.group_id, self.env.ref("base.group_user"))
        self.assertEqual(step.sequence, 1)
        self.assertTrue(binding.category_id.notify_sequentially)

    def test_further_steps_join_the_same_binding_up_to_order_nine(self):
        steps = self.Step.browse([self._add_step().id for _ in range(10)])
        self.assertEqual(len(steps.category_id), 1)
        self.assertEqual(steps.mapped("sequence"), [1, 2, 3, 4, 5, 6, 7, 8, 9, 9])

    def test_an_action_button_named_by_xmlid_is_bound_to_that_action(self):
        step = self._add_step(method=False, action_id="base.action_model_data")
        binding = self.Binding.search(
            [("action_id", "=", self.env.ref("base.action_model_data").id)]
        )
        self.assertEqual(step.category_id, binding.category_id)

    def test_the_approvers_list_edits_plain_members_and_keeps_delegations(self):
        step = self._add_step()
        step.user_ids = [Command.set((self.first | self.second).ids)]
        self.assertEqual(step.member_ids.user_id, self.first | self.second)
        step.member_ids = [
            Command.create(
                {
                    "user_id": self.delegate.id,
                    "date_end": fields.Date.today() + datetime.timedelta(days=5),
                    "delegated_by_id": self.first.id,
                }
            )
        ]
        step.user_ids = [Command.set(self.second.ids)]
        self.assertEqual(step.member_ids.user_id, self.second | self.delegate)
        self.assertEqual(step.user_ids, self.second | self.delegate)

    def test_the_steps_action_lists_the_buttons_steps(self):
        step = self._add_step()
        action = self.Binding.action_open_button_steps(
            "res.partner", "action_archive", False
        )
        self.assertEqual(self.Step.search(action["domain"]), step)
        self.assertEqual(action["context"]["default_category_id"], step.category_id.id)

    def test_a_button_whose_steps_are_all_archived_is_no_longer_gated(self):
        """Studio's test_disable_approvals: archiving the last rule lifts the gate."""
        step = self._add_step()
        user = self.env["res.users"].create(
            {
                "name": "editor_caller",
                "login": "editor_caller",
                "email": "editor_caller@test.com",
                "group_ids": [
                    Command.link(self.env.ref("base.group_partner_manager").id)
                ],
            }
        )
        partner = self.env["res.partner"].create({"name": "Editor Partner"})
        spec = {
            "model": "res.partner",
            "res_id": partner.id,
            "method": "action_archive",
            "action_id": False,
        }
        self.assertTrue(
            self.Binding.with_user(user).get_button_approvals([spec])[0]["gated"]
        )
        step.active = False
        self.assertFalse(
            self.Binding.with_user(user).get_button_approvals([spec])[0]["gated"]
        )
        partner.with_user(user).action_archive()
        self.assertFalse(
            partner.active, "a binding that asks nobody does not stop the call"
        )

    def test_approvers_given_without_a_group_satisfy_the_pool_check(self):
        """The pool check waits for the approvers list to become members."""
        category = self.env["approval.category"].create({"name": "No group"})
        step = self.Step.create(
            {
                "category_id": category.id,
                "name": "Members only",
                "user_ids": [Command.set(self.first.ids)],
            }
        )
        self.assertEqual(step.member_ids.user_id, self.first)
        step.write({"group_id": False, "user_ids": [Command.set(self.second.ids)]})
        self.assertEqual(step.member_ids.user_id, self.second)
