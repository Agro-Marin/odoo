from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.base.models.ir_config_parameter import _default_parameters


class TestIrConfigParameter(TransactionCase):
    def test_default_parameters(self):
        """Check the behavior of _default_parameters
        when updating keys and deleting records."""
        for key in _default_parameters:
            config_parameter = self.env["ir.config_parameter"].search(
                [("key", "=", key)], limit=1
            )
            with self.assertRaises(ValidationError):
                config_parameter.unlink()

            new_key = f"{key}_updated"
            with self.assertRaises(ValidationError):
                config_parameter.write({"key": new_key})


class TestSetGetParam(TransactionCase):
    def test_set_get_param_lifecycle(self):
        """ICP-T1: cover set_param create/update/no-op/unlink and get_param fallback."""
        ICP = self.env["ir.config_parameter"]
        key = "base.test_set_get_param"
        # missing key: get_param returns the supplied default, else False
        self.assertEqual(ICP.get_param(key, default="fallback"), "fallback")
        self.assertEqual(ICP.get_param(key), False)
        # create branch: returns False (no previous value)
        self.assertEqual(ICP.set_param(key, "v1"), False)
        self.assertEqual(ICP.get_param(key), "v1")
        # update branch: returns the previous value
        self.assertEqual(ICP.set_param(key, "v2"), "v1")
        self.assertEqual(ICP.get_param(key), "v2")
        # non-string values are coerced to text on store (as init does with ints)
        self.assertEqual(ICP.set_param(key, 42), "v2")
        self.assertEqual(ICP.get_param(key), "42")
        # no-op update: identical value still returns the previous value
        self.assertEqual(ICP.set_param(key, "42"), "42")
        # unlink branch: False/None clears the parameter, returns previous value
        self.assertEqual(ICP.set_param(key, False), "42")
        self.assertEqual(ICP.get_param(key), False)
        # clearing a missing key is a no-op that returns False
        self.assertEqual(ICP.set_param(key, False), False)
