from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestResConfig(TransactionCase):
    def test_00_add_parameter_with_default_value(self):
        """Check if parameters with a default value are saved in the ir_config_parameter table"""

        self.env["res.config.test"].create({}).execute()
        self.assertEqual(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("resConfigTest.parameter1"),
            str(1000),
            "The parameter is not saved with its default value",
        )

        with patch(
            "odoo.addons.base.models.ir_config_parameter.IrConfig_Parameter.set_param"
        ) as set_param_mock:
            self.env["res.config.test"].create({}).execute()

        set_param_mock.assert_not_called()

    def test_01_boolean_parameter_default_true_round_trip(self):
        """RCFG-B1: a boolean config_parameter field with default=True must
        display True on a fresh database (no parameter stored yet), and saving
        False must persist "False" instead of deleting the parameter."""
        ICP = self.env["ir.config_parameter"].sudo()
        # fresh database: the parameter is not stored, the field default wins
        self.assertFalse(ICP.get_param("resConfigTest.parameter3"))
        settings = self.env["res.config.test"].create({})
        self.assertTrue(
            settings.param3,
            "The default=True of a boolean config_parameter field must show "
            "as checked when the parameter is not stored",
        )
        settings.execute()
        self.assertEqual(ICP.get_param("resConfigTest.parameter3"), "True")

        # unchecking must persist "False", not delete the parameter
        self.env["res.config.test"].create({"param3": False}).execute()
        self.assertEqual(ICP.get_param("resConfigTest.parameter3"), "False")

        # reopening the settings must show False, not revert to the default
        self.assertFalse(self.env["res.config.test"].create({}).param3)

    def test_02_mixed_group_field_types_save(self):
        """RCFG-S1: saving settings where boolean and selection group_ fields
        coexist must not raise (sorted() must not compare bool with str)."""
        settings = self.env["res.config.test"].create(
            {"group_test_checkbox": True, "group_test_selection": "0"}
        )
        # would raise "TypeError: '<' not supported between instances of
        # 'str' and 'bool'" before the sort key normalization
        settings.execute()
        group_user = self.env.ref("base.group_user")
        self.assertIn(
            self.env.ref("base.group_multi_currency"),
            group_user.all_implied_ids,
        )
