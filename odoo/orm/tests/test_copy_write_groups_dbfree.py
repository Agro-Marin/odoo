from types import SimpleNamespace

import pytest

from odoo import fields, models
from odoo.exceptions import AccessError
from odoo.orm.domain import Domain
from odoo.orm.model_test_env import model_test_env

_MOD = "test_copy_write_groups_dbfree"


def _is_price_manager(records):
    return bool(records.env.context.get("price_manager"))


class Template(models.Model):
    _name = "cwg.template"
    _module = _MOD
    _description = "a template whose price only a price manager decides"
    _log_access = False

    name = fields.Char()
    price = fields.Float(write_groups=_is_price_manager)
    listed = fields.Boolean(default=True, write_groups=_is_price_manager)
    hidden_price = fields.Float(write_groups=_is_price_manager, copy=False)


class Variant(models.Model):
    _name = "cwg.variant"
    _module = _MOD
    _description = "a variant delegating to its template"
    _log_access = False
    _inherits = {"cwg.template": "template_id"}

    template_id = fields.Many2one("cwg.template", required=True, ondelete="cascade")
    code = fields.Char()


class IrAccess(models.AbstractModel):
    _name = "ir.access"
    _module = _MOD + "_access"
    _description = "ir.access (test stub)"

    def _policy_signature(self):
        return (self.env.uid, *self._get_access_context())

    def _get_access_context(self):
        yield None

    def _bound_access_rows(self, model_name, operation):
        return [Domain.TRUE], []


class IrModel(models.AbstractModel):
    _name = "ir.model"
    _module = _MOD + "_model"
    _description = "ir.model (test stub)"

    def _get(self, model_name):
        return SimpleNamespace(name=self.env[model_name]._description)


class Users(models.AbstractModel):
    _name = "res.users"
    _module = _MOD + "_users"
    _description = "res.users (test stub)"

    def _has_group(self, group_ext_id):
        return False


@pytest.fixture
def env():
    with model_test_env(Template, Variant, IrAccess, IrModel, Users) as env:
        yield env


def _template(env):
    return env["cwg.template"].create(
        {"name": "t", "price": 10.0, "listed": False, "hidden_price": 3.0}
    )


def _user(env, **context):
    return env(user=2, su=False, context=context)


def test_copy_withholds_a_write_gated_value_the_user_may_not_set(env):
    template = _template(env)

    duplicate = template.with_env(_user(env)).copy()

    assert duplicate.name == "t"
    assert duplicate.price == 0.0
    assert duplicate.listed is True


def test_copy_keeps_a_write_gated_value_the_user_may_set(env):
    template = _template(env)

    duplicate = template.with_env(_user(env, price_manager=True)).copy()

    assert (duplicate.price, duplicate.listed) == (10.0, False)


def test_an_explicit_default_for_a_gated_field_is_still_refused(env):
    template = _template(env).with_env(_user(env))

    with pytest.raises(AccessError):
        template.copy({"price": 5.0})
    with pytest.raises(AccessError):
        template.env["cwg.template"].create({"name": "n", "price": 5.0})


def test_superuser_copy_carries_every_gated_value(env):
    duplicate = _template(env).copy()

    assert (duplicate.price, duplicate.listed) == (10.0, False)


def test_copy_of_a_delegating_record_withholds_the_parent_gated_value(env):
    variant = env["cwg.variant"].create(
        {"name": "v", "price": 7.0, "listed": False, "code": "C"}
    )

    duplicate = variant.with_env(_user(env)).copy()

    assert duplicate.template_id != variant.template_id
    assert (duplicate.name, duplicate.code) == ("v", "C")
    assert (duplicate.price, duplicate.listed) == (0.0, True)
