from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestOverrides(TransactionCase):
    def test_creates(self):
        for model_env in self.env.values():
            if model_env._abstract:
                continue
            self.assertEqual(
                model_env.create([]),
                model_env.browse(),
                "Invalid create return value for model %s" % model_env._name,
            )

    def test_writes(self):
        for model_env in self.env.values():
            if model_env._abstract:
                continue
            try:
                self.assertEqual(
                    model_env.browse().write({}),
                    True,
                    "Invalid write return value for model %s" % model_env._name,
                )
            except UserError:
                continue

    def test_default_get(self):
        for model_env in self.env.values():
            if model_env._transient:
                continue
            try:
                self.assertEqual(
                    model_env.browse().default_get([]),
                    {},
                    "Invalid default_get return value for model %s" % model_env._name,
                )
            except UserError:
                continue

    def test_unlink(self):
        for model_env in self.env.values():
            if model_env._abstract:
                continue
            self.assertEqual(
                model_env.browse().unlink(),
                True,
                "Invalid unlink return value for model %s" % model_env._name,
            )
