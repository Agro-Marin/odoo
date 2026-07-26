from unittest.mock import patch

import odoo
from odoo.exceptions import ConcurrencyError, ValidationError
from odoo.modules.registry import Registry
from odoo.tests import common
from odoo.tests.common import BaseCase, TransactionCase
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
        """ICP-C1: when the key exists but the search missed it, set_param must
        fall back to the update path instead of aborting the whole transaction
        on the unique constraint.

        The row is visible to this transaction (a record rule hiding it, say);
        the cross-transaction race, where it is not, is
        ``test_set_param_concurrent_create_is_retryable``.
        """
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


class TestSetParamConcurrency(BaseCase):
    """set_param racing a concurrent transaction on the same new key."""

    KEY = "base.test_set_param_cross_tx_race"

    def setUp(self):
        super().setUp()
        self.addCleanup(self._drop_key)
        self._drop_key()

    def _drop_key(self):
        registry = Registry(common.get_db_name())
        with registry.cursor() as cr:
            env = odoo.api.Environment(cr, common.ADMIN_USER_ID, {})
            env["ir.config_parameter"].search([("key", "=", self.KEY)]).unlink()

    @mute_logger("odoo.db.cursor")
    def test_set_param_concurrent_create_is_retryable(self):
        """The loser of a create race asks for a request replay.

        Both transactions find no row for the key and both insert.  The loser
        used to re-``search`` -- which cannot see the winner's row under
        ``REPEATABLE READ`` -- and then ``create`` again, so the caller got a
        raw ``ir_config_parameter_key_uniq`` violation.  It must raise
        ``ConcurrencyError`` instead, which ``retrying`` replays.
        """
        registry = Registry(common.get_db_name())
        with registry.cursor() as cr_a, registry.cursor() as cr_b:
            env_a = odoo.api.Environment(cr_a, common.ADMIN_USER_ID, {})
            env_b = odoo.api.Environment(cr_b, common.ADMIN_USER_ID, {})
            # pin both snapshots while the key does not exist
            for env in (env_a, env_b):
                env["ir.config_parameter"].search_count([("key", "=", self.KEY)])

            env_a["ir.config_parameter"].set_param(self.KEY, "winner")
            cr_a.commit()

            with self.assertRaises(ConcurrencyError):
                env_b["ir.config_parameter"].set_param(self.KEY, "loser")

            # what ``retrying`` does: roll back, then run the request again
            cr_b.rollback()
            env_b = odoo.api.Environment(cr_b, common.ADMIN_USER_ID, {})
            self.assertEqual(
                env_b["ir.config_parameter"].set_param(self.KEY, "loser"), "winner"
            )
