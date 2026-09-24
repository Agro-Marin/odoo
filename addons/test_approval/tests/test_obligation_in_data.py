from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestObligationInData(TransactionCase):
    """A code gate is data now: a verb the model declares, and a binding a module ships."""

    def test_every_shipped_obligation_is_noupdate_module_data(self):
        obligations = (
            self.env["approval.binding"]
            .with_context(active_test=False)
            .search([("origin", "=", "module")])
        )
        self.assertTrue(obligations)
        data = self.env["ir.model.data"].search(
            [("model", "=", "approval.binding"), ("res_id", "in", obligations.ids)]
        )
        self.assertEqual(
            set(data.mapped("res_id")),
            set(obligations.ids),
            "an obligation a module ships has the module's xml id",
        )
        self.assertTrue(
            all(data.mapped("noupdate")),
            "an upgrade must not undo the mode an operator chose",
        )
        self.assertFalse(obligations.filtered("category_id"))
        self.assertFalse(obligations.filtered(lambda binding: not binding.verb))

    def test_no_model_declares_a_gate_outside_its_verbs(self):
        declared = sorted(
            model_name
            for model_name, model_cls in self.env.registry.items()
            if hasattr(model_cls, "_approval_operations")
            or hasattr(model_cls, "_operation_checkpoints")
        )
        self.assertEqual(declared, [])

    def test_every_approval_lifecycle_confirms_into_its_confirmed_state(self):
        lifecycle = self.env.registry["mixin.approval.lifecycle"]
        for model_name, model_cls in self.env.registry.items():
            if model_cls._abstract or not issubclass(model_cls, lifecycle):
                continue
            with self.subTest(model=model_name):
                verb = self.env.registry.model_verbs.get(model_name, {}).get("confirm")
                self.assertIsNotNone(verb, "an approval lifecycle declares confirm")
                self.assertEqual(
                    verb.transition[2],
                    self.env[model_name]._get_confirmed_state(),
                    "confirm moves the document into the state it is confirmed in",
                )
