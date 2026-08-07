from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestOverrides(TransactionCase):
    def _concrete_models(self):
        return [model for model in self.env.values() if not model._abstract]

    def test_creates(self):
        for model_env in self._concrete_models():
            with self.subTest(model=model_env._name):
                self.assertEqual(
                    model_env.create([]),
                    model_env.browse(),
                    "Invalid create return value for model %s" % model_env._name,
                )

    def test_writes(self):
        for model_env in self._concrete_models():
            with self.subTest(model=model_env._name):
                try:
                    result = model_env.browse().write({})
                except UserError as exc:
                    self.fail(
                        "%s.write() raised on an empty recordset: %s"
                        % (model_env._name, exc)
                    )
                self.assertEqual(
                    result,
                    True,
                    "Invalid write return value for model %s" % model_env._name,
                )

    def test_default_get(self):
        for model_env in self.env.values():
            if model_env._transient:
                continue
            with self.subTest(model=model_env._name):
                try:
                    result = model_env.browse().default_get([])
                except UserError as exc:
                    self.fail(
                        "%s.default_get() raised on an empty recordset: %s"
                        % (model_env._name, exc)
                    )
                self.assertEqual(
                    result,
                    {},
                    "Invalid default_get return value for model %s" % model_env._name,
                )

    def test_unlink(self):
        for model_env in self._concrete_models():
            with self.subTest(model=model_env._name):
                self.assertEqual(
                    model_env.browse().unlink(),
                    True,
                    "Invalid unlink return value for model %s" % model_env._name,
                )
