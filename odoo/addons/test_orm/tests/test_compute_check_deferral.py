from odoo.tests.common import TransactionCase


class TestComputeCheckDeferral(TransactionCase):
    def test_a_nested_compute_checks_its_constraints_after_the_outer_one_assigns(self):
        record = self.env["test_orm.compute_check"].create({"name": "a"})
        self.assertEqual(record.code, "A")
        self.assertEqual(record.label, "a")
