from odoo.tests import TransactionCase, tagged

from odoo.addons.approval_app import (
    _adopt_engine_shell,
    _pre_init_refuse_to_reset_the_engine_shell,
)


@tagged("post_install", "-at_install")
class TestEngineShellAdoption(TransactionCase):
    def _hand_back_to_the_engine(self, name):
        row = self.env["ir.model.data"].search(
            [("module", "=", "approval_app"), ("name", "=", name)]
        )
        row.module = "approval"
        self.env.flush_all()
        return row

    def test_a_database_from_before_the_split_hands_its_records_over(self):
        category = self.env.ref("approval_app.approval_category_data_business_trip")
        row = self._hand_back_to_the_engine("approval_category_data_business_trip")

        _adopt_engine_shell(self.env.cr)
        row.invalidate_recordset()

        self.assertEqual(row.module, "approval_app")
        self.assertEqual(row.res_id, category.id)

    def test_installing_over_records_the_engine_still_owns_is_refused(self):
        self._hand_back_to_the_engine("approval_category_data_business_trip")
        with self.assertRaisesRegex(RuntimeError, "Upgrade approval in the same run"):
            _pre_init_refuse_to_reset_the_engine_shell(self.env)

    def test_installing_over_records_already_handed_over_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "Mark it for upgrade instead"):
            _pre_init_refuse_to_reset_the_engine_shell(self.env)
