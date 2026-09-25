from odoo.tests import TransactionCase, tagged
from odoo.tools import convert_file


@tagged("post_install", "-at_install")
class TestDemoData(TransactionCase):
    def test_demo_board_loads(self):
        convert_file(
            self.env,
            module="account_depreciation",
            filename="demo/account_asset_demo.xml",
            idref={},
            mode="init",
            noupdate=False,
        )
        board = self.env.ref("account_depreciation.account_asset_model_demo")
        self.assertEqual(board.value_original, 1000)
        self.assertEqual(board.asset_group_id.name, "Odoo Office")
