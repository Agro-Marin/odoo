import inspect

from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.ir_actions_server import IrActionsServer


@tagged("post_install", "-at_install")
class TestServerActionEvalContext(TransactionCase):
    def test_eval_context_requires_action(self):
        parameter = inspect.signature(IrActionsServer._prepare_eval_context).parameters[
            "action"
        ]
        self.assertIs(
            parameter.default,
            inspect.Parameter.empty,
            "ir.actions.server._prepare_eval_context must require its action",
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
        eval_context = self.env["ir.actions.server"]._prepare_eval_context(action)
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

    def _gated_crud_action(self, **vals):
        return self.env["ir.actions.server"].create(
            {
                "name": "audit gated crud",
                "model_id": self.env["ir.model"]._get_id(self.model_name),
                "group_ids": [Command.set(self.env.ref("base.group_user").ids)],
                **vals,
            }
        )

    def test_group_gated_create_still_needs_create_access_on_its_target(self):
        currency_model = self.env["ir.model"]._get_id("res.currency")
        action = self._gated_crud_action(
            state="object_create",
            model_id=currency_model,
            crud_model_id=currency_model,
            value="ZZQ",
        )
        with self.assertRaises(AccessError):
            action.with_user(self.user).run()
        self.assertFalse(
            self.env["res.currency"]
            .with_context(active_test=False)
            .search_count([("name", "=", "ZZQ")])
        )

    def test_group_gated_write_still_needs_write_access_on_its_records(self):
        rate = self.env["res.currency.rate"].create(
            {
                "name": "2026-01-01",
                "rate": 1.5,
                "currency_id": self.env.company.currency_id.id,
            }
        )
        action = self._gated_crud_action(
            state="object_write",
            update_path="rate",
            evaluation_type="value",
            value="2.5",
        )
        with self.assertRaises(AccessError):
            action.with_user(self.user).with_context(
                active_model=self.model_name, active_id=rate.id, active_ids=rate.ids
            ).run()
        self.assertNotEqual(rate.rate, 2.5)

    def test_elevated_caller_still_bypasses(self):
        self.action.sudo().with_user(self.user).sudo().run()
