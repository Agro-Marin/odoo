from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

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
        self.assertEqual(ICP.get_param(key, default="fallback"), "fallback")
        self.assertEqual(ICP.get_param(key), False)
        self.assertEqual(ICP.set_param(key, "v1"), False)
        self.assertEqual(ICP.get_param(key), "v1")
        self.assertEqual(ICP.set_param(key, "v2"), "v1")
        self.assertEqual(ICP.get_param(key), "v2")
        self.assertEqual(ICP.set_param(key, 42), "v2")
        self.assertEqual(ICP.get_param(key), "42")
        self.assertEqual(ICP.set_param(key, "42"), "42")
        self.assertEqual(ICP.set_param(key, False), "42")
        self.assertEqual(ICP.get_param(key), False)
        self.assertEqual(ICP.set_param(key, False), False)

    @mute_logger("odoo.db.cursor")
    def test_set_param_create_race(self):
        """ICP-C1: when a concurrent transaction creates the key between the
        search and the insert, set_param must fall back to the update path
        instead of aborting the whole transaction on the unique constraint."""
        ICP = self.env["ir.config_parameter"]
        key = "base.test_set_param_race"
        ICP.set_param(key, "concurrent")
        cls = self.registry["ir.config_parameter"]
        original_search = cls.search
        missed = []

        def racy_search(model, domain, *args, **kwargs):
            if not missed and domain == [("key", "=", key)]:
                missed.append(True)
                return model.browse()
            return original_search(model, domain, *args, **kwargs)

        with patch.object(cls, "search", racy_search):
            old = ICP.set_param(key, "winner")

        self.assertTrue(missed, "the racy search stub was not exercised")
        self.assertEqual(old, "concurrent")
        self.assertEqual(ICP.get_param(key), "winner")
