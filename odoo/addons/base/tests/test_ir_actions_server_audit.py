import inspect

from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.ir_actions_server import IrActionsServer


@tagged("post_install", "-at_install")
class TestServerActionEvalContext(TransactionCase):
    def test_eval_context_requires_action(self):
        parameter = inspect.signature(IrActionsServer._get_eval_context).parameters[
            "action"
        ]
        self.assertIs(
            parameter.default,
            inspect.Parameter.empty,
            "ir.actions.server._get_eval_context must require its action",
        )

    def test_eval_context_with_action(self):
        action = self.env["ir.actions.server"].create(
            {
                "name": "audit-eval-ctx",
                "model_id": self.env["ir.model"]._get("res.partner").id,
                "state": "code",
                "code": "True",
            }
        )
        eval_context = self.env["ir.actions.server"]._get_eval_context(action)
        self.assertEqual(eval_context["model"]._name, "res.partner")
        self.assertIn("env", eval_context)
        self.assertIn("log", eval_context)


@tagged("post_install", "-at_install")
class TestSelectionTargetModelCache(TransactionCase):
    def test_returns_immutable_tuple_of_tuples(self):
        ServerAction = self.env["ir.actions.server"]
        result = ServerAction._selection_target_model()
        self.assertIsInstance(result, tuple)
        self.assertTrue(result, "expected at least one model in the selection")
        self.assertTrue(
            all(isinstance(item, tuple) and len(item) == 2 for item in result)
        )
        self.assertIs(ServerAction._selection_target_model(), result)


@tagged("post_install", "-at_install")
class TestServerActionModelAccessGate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_name = "res.currency.rate"
        cls.user = cls.env["res.users"].create(
            {
                "name": "audit gate user",
                "login": "audit_gate_user",
                "group_ids": [Command.set(cls.env.ref("base.group_user").ids)],
            }
        )
        cls.action = cls.env["ir.actions.server"].create(
            {
                "name": "audit gate action",
                "model_id": cls.env["ir.model"]._get_id(cls.model_name),
                "state": "code",
                "code": "True",
            }
        )

    def test_model_write_access_is_required_without_records(self):
        with self.assertRaises(AccessError):
            self.env(user=self.user)[self.model_name].check_access("write")
        self.assertFalse(self.action.group_ids)
        with self.assertRaises(AccessError):
            self.action.with_user(self.user).run()

    def test_group_gated_action_still_bypasses_model_acl(self):
        self.action.group_ids = self.env.ref("base.group_user")
        self.action.with_user(self.user).run()

    def test_elevated_caller_still_bypasses(self):
        self.action.sudo().with_user(self.user).sudo().run()
