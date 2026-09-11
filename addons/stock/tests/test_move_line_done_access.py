from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestMoveLineDoneAccess(TransactionCase):
    def test_no_lot_check_reads_no_lots(self):
        user = new_test_user(
            self.env, login="no_stock_rights", groups="base.group_user"
        )
        self.assertFalse(user.has_group("stock.group_stock_user"))
        move_lines = self.env["stock.move.line"].with_user(user)
        with self.assertQueryCount(0):
            self.assertFalse(move_lines._update_done_lots())
