from odoo.tests import TransactionCase
from odoo.tools.populate import populate_models


class TestPopulate(TransactionCase):
    def _count(self, model):
        return self.env[model].search_count([])

    def test_populate_inherits_model_does_not_raise(self):
        users_before = self._count("res.users")
        partners_before = self._count("res.partner")

        populate_models({self.env["res.users"]: 2}, ord("_"))
        self.env.invalidate_all()

        self.assertEqual(self._count("res.users"), users_before * 3)
        self.assertGreater(self._count("res.partner"), partners_before)

    def test_populate_plain_model(self):
        partners_before = self._count("res.partner")
        populate_models({self.env["res.partner"]: 2}, ord("_"))
        self.env.invalidate_all()
        self.assertEqual(self._count("res.partner"), partners_before * 3)
