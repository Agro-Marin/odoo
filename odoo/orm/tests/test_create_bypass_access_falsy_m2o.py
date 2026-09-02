import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_create_bypass_access_falsy_m2o"

ACCESS_CALLS: list = []


class Guarded(models.Model):
    _name = "guarded.target"
    _module = _MOD
    _description = "Guarded Target"

    name = fields.Char()

    def check_access(self, operation):
        ACCESS_CALLS.append((self._ids, operation))


class Holder(models.Model):
    _name = "bypass.holder"
    _module = _MOD
    _description = "Bypass Holder"

    name = fields.Char()
    target_id = fields.Many2one("guarded.target", bypass_search_access=True)

    def check_access(self, operation):
        pass


@pytest.fixture
def env():
    ACCESS_CALLS.clear()
    gen = model_test_env(Guarded, Holder)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


def test_a_falsy_m2o_in_vals_triggers_no_comodel_access_check(env):
    user = env["res.users"].create([{"name": "limited"}])
    as_user = env(user=user.id)
    assert not as_user.su

    as_user["bypass.holder"].create([{"name": "x", "target_id": False}])
    assert ACCESS_CALLS == [], (
        f"creating with a falsy many2one still ran check_access on the "
        f"comodel: {ACCESS_CALLS}"
    )


def test_a_real_m2o_in_vals_still_checks_the_comodel(env):
    target = env["guarded.target"].create([{"name": "t"}])
    user = env["res.users"].create([{"name": "limited"}])
    as_user = env(user=user.id)
    ACCESS_CALLS.clear()

    as_user["bypass.holder"].create([{"name": "x", "target_id": target.id}])
    assert (tuple(target._ids), "read") in ACCESS_CALLS
