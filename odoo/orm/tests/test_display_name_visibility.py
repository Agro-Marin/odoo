import pytest

from odoo import fields, models
from odoo.exceptions import AccessError
from odoo.orm.model_test_env import model_test_env

_MOD = "test_display_name_visibility"


def _deny(self, operation):
    return self, lambda: AccessError("denied")


class Hidden(models.Model):
    _name = "visibility.hidden"
    _module = _MOD
    _description = "Hidden Target"

    name = fields.Char()

    _check_access = _deny


class Named(models.Model):
    _name = "visibility.named"
    _module = _MOD
    _description = "Named Target"

    name = fields.Char()

    _check_access = _deny

    def _get_display_name_visible_ids(self):
        return set(self._ids)


class Holder(models.Model):
    _name = "visibility.holder"
    _module = _MOD
    _description = "Holder"

    name = fields.Char()
    hidden_id = fields.Many2one("visibility.hidden")
    named_id = fields.Many2one("visibility.named")

    def _check_access(self, operation):
        return None


@pytest.fixture
def env():
    gen = model_test_env(Hidden, Named, Holder)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


@pytest.fixture
def as_user(env):
    user = env["res.users"].create([{"name": "limited"}])
    limited = env(user=user.id)
    assert not limited.su
    return limited


def test_the_default_hook_denies_every_id(env, as_user):
    hidden = env["visibility.hidden"].create([{"name": "h"}]).with_env(as_user)
    assert hidden._get_display_name_visible_ids() == set()
    assert not hidden._filtered_display_name_access()


def test_an_opted_in_model_keeps_its_hidden_records_in_the_filtered_set(env, as_user):
    named = env["visibility.named"].create([{"name": "n1"}, {"name": "n2"}])
    named = named.with_env(as_user)
    assert not named._filtered_access("read")
    assert named._filtered_display_name_access() == named


def test_the_superuser_sees_every_label(env):
    hidden = env["visibility.hidden"].create([{"name": "h"}])
    assert hidden._filtered_display_name_access() == hidden


def test_convert_to_read_follows_the_hook(env, as_user):
    hidden = env["visibility.hidden"].create([{"name": "h"}])
    named = env["visibility.named"].create([{"name": "n"}])
    holder = env["visibility.holder"].create(
        [{"name": "x", "hidden_id": hidden.id, "named_id": named.id}]
    )
    [values] = holder.with_env(as_user).read(["hidden_id", "named_id"])
    assert values["hidden_id"] is False
    assert values["named_id"] == (named.id, "n")
    [raw] = holder.with_env(as_user).read(["hidden_id", "named_id"], load=None)
    assert raw["hidden_id"] == hidden.id
    assert raw["named_id"] == named.id
