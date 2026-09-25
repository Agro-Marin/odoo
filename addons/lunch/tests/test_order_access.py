from odoo.exceptions import AccessError
from odoo.tests import new_test_user

from odoo.addons.lunch.tests.common import TestsCommon


class TestOrderWriteReach(TestsCommon):
    def setUp(self):
        super().setUp()
        self.eater = new_test_user(
            self.env, "lunch-eater", "base.group_user,lunch.group_lunch_user"
        )
        self.colleague = new_test_user(
            self.env, "lunch-colleague", "base.group_user,lunch.group_lunch_user"
        )
        Order = self.env["lunch.order"]
        where = {"lunch_location_id": self.location_office_1.id, "quantity": 1}
        self.received = Order.create(
            {
                **where,
                "product_id": self.product_sandwich_tuna.id,
                "user_id": self.eater.id,
            }
        )
        self.received.state = "confirmed"
        self.mine = Order.create(
            {**where, "product_id": self.product_pizza.id, "user_id": self.eater.id}
        )
        self.theirs = Order.create(
            {**where, "product_id": self.product_pizza.id, "user_id": self.colleague.id}
        )

    def test_a_user_changes_their_own_open_order(self):
        self.mine.with_user(self.eater).write({"note": "no olives"})
        self.assertEqual(self.mine.note, "no olives")

    def test_a_user_does_not_change_a_colleague_s_order(self):
        with self.assertRaises(AccessError):
            self.theirs.with_user(self.eater).write({"note": "no olives"})

    def test_a_user_does_not_change_a_received_order(self):
        with self.assertRaises(AccessError):
            self.received.with_user(self.eater).write({"note": "late"})

    def test_a_manager_changes_any_order(self):
        (self.theirs | self.received).with_user(self.manager).write({"note": "fixed"})
        self.assertEqual(set((self.theirs | self.received).mapped("note")), {"fixed"})
