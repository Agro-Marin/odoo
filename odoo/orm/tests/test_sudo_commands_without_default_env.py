"""``_check_sudo_commands`` must not crash when there is no default environment.

``Transaction.default_env`` is only set for an environment built with a truthy
integer uid, and ``Transaction.flush`` already carries a fallback for the state
where none was. ``_RelationalMulti._check_sudo_commands`` read
``transaction.default_env.uid`` with no guard, so an x2many write touching one
of the models that set ``_allow_sudo_commands = False`` raised
``AttributeError`` instead of refusing the write.
"""

import unittest

from odoo import fields, models
from odoo.exceptions import AccessError
from odoo.orm.model_test_env import model_test_env
from odoo.orm.runtime import Environment

_MOD = "test_sudo_commands_without_default_env"


class SGuardLine(models.Model):
    _name = "s.guard.line"
    _module = _MOD
    _description = "Guarded line"
    _allow_sudo_commands = False

    name = fields.Char()
    host_id = fields.Many2one("s.guard.host")


class SGuardHost(models.Model):
    _name = "s.guard.host"
    _module = _MOD
    _description = "Guard host"

    name = fields.Char()
    line_ids = fields.One2many("s.guard.line", "host_id")


class OpenLine(models.Model):
    _name = "s.open.line"
    _module = _MOD
    _description = "Unguarded line"

    name = fields.Char()
    host_id = fields.Many2one("s.open.host")


class OpenHost(models.Model):
    _name = "s.open.host"
    _module = _MOD
    _description = "Open host"

    name = fields.Char()
    line_ids = fields.One2many("s.open.line", "host_id")


class TestSudoCommandsWithoutDefaultEnv(unittest.TestCase):
    MODELS = (SGuardHost, SGuardLine, OpenHost, OpenLine)

    def test_the_state_is_reachable(self):
        # environment.py only adopts a default env for a *truthy* integer uid,
        # so a transaction whose environments were all built with uid 0 never
        # gets one. This is the rule the guard depends on.
        with model_test_env(*self.MODELS) as env:
            transaction = env.transaction
            transaction.default_env = None
            Environment(env.cr, 0, {})
            self.assertIsNone(
                transaction.default_env,
                "uid 0 must not become the transaction's default environment",
            )

    def test_a_guarded_comodel_refuses_instead_of_raising_AttributeError(self):
        with model_test_env(*self.MODELS) as env:
            env.transaction.default_env = None
            field = env["s.guard.host"]._fields["line_ids"]
            with self.assertRaises(AccessError) as capture:
                field._check_sudo_commands(env["s.guard.line"])
            self.assertIn("s.guard.line", str(capture.exception))

    def test_an_unguarded_comodel_is_untouched_without_a_default_env(self):
        with model_test_env(*self.MODELS) as env:
            env.transaction.default_env = None
            field = env["s.open.host"]._fields["line_ids"]
            comodel = env["s.open.line"]
            self.assertIs(field._check_sudo_commands(comodel), comodel)

    def test_an_unguarded_comodel_is_untouched(self):
        with model_test_env(*self.MODELS) as env:
            field = env["s.open.host"]._fields["line_ids"]
            comodel = env["s.open.line"]
            self.assertIs(field._check_sudo_commands(comodel), comodel)

    def test_a_real_default_env_still_downgrades(self):
        with model_test_env(*self.MODELS) as env:
            user_env = Environment(env.cr, 7, {})
            env.transaction.default_env = user_env
            field = env["s.guard.host"]._fields["line_ids"]
            downgraded = field._check_sudo_commands(env["s.guard.line"].sudo())
            self.assertFalse(downgraded.env.su, "sudo must be dropped")
            self.assertEqual(downgraded.env.uid, 7, "and the real user adopted")


if __name__ == "__main__":
    unittest.main()
