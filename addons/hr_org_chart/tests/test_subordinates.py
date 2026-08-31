from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSubordinates(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Employee = cls.env["hr.employee"]
        cls.ceo = Employee.create({"name": "OC CEO"})
        cls.cto = Employee.create({"name": "OC CTO", "parent_id": cls.ceo.id})
        cls.dev_1 = Employee.create({"name": "OC Dev 1", "parent_id": cls.cto.id})
        cls.dev_2 = Employee.create({"name": "OC Dev 2", "parent_id": cls.cto.id})

    def test_direct_child_count(self):
        self.ceo.invalidate_recordset(["child_count"])
        self.cto.invalidate_recordset(["child_count"])
        self.assertEqual(self.ceo.child_count, 1)
        self.assertEqual(self.cto.child_count, 2)
        self.assertEqual(self.dev_1.child_count, 0)

    def test_all_subordinates_are_transitive(self):
        subordinates = self.ceo._get_subordinates()
        self.assertEqual(subordinates, self.cto | self.dev_1 | self.dev_2)
        self.assertEqual(self.ceo.child_all_count, 3)

    def test_leaf_has_no_subordinates(self):
        self.assertFalse(self.dev_1._get_subordinates())
        self.assertEqual(self.dev_1.child_all_count, 0)
