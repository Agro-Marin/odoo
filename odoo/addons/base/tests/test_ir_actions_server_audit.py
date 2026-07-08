"""Audit tests for ir.actions.server.

Covers the required ``action`` parameter of ``_get_eval_context`` (the override
derives its context from ``action.model_id``, so a missing action could only
crash later on ``None.model_id``) and the immutability of the ormcached
``_selection_target_model`` result.
"""

import inspect

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.ir_actions_server import IrActionsServer


@tagged("post_install", "-at_install")
class TestServerActionEvalContext(TransactionCase):
    """_get_eval_context requires the server action it is evaluated for."""

    def test_eval_context_requires_action(self):
        # Lock the base override's signature rather than calling with zero
        # args: downstream overrides (e.g. mail's) may still declare an
        # action=None default, so the runtime failure mode of a zero-arg call
        # depends on which modules are installed. The audited contract is
        # that ir.actions.server's own override takes a required action.
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
    """The ormcached model-selection list must be an immutable tuple: the
    cached value is shared across callers, so a mutable list would let one
    caller corrupt the cache for everyone."""

    def test_returns_immutable_tuple_of_tuples(self):
        ServerAction = self.env["ir.actions.server"]
        result = ServerAction._selection_target_model()
        self.assertIsInstance(result, tuple)
        self.assertTrue(result, "expected at least one model in the selection")
        self.assertTrue(
            all(isinstance(item, tuple) and len(item) == 2 for item in result)
        )
        # Warm-cache call returns the very same shared object.
        self.assertIs(ServerAction._selection_target_model(), result)
