from odoo import fields, models
from odoo.orm.model_test_env import model_test_env
from odoo.orm.primitives import SUPERUSER_ID


class Thing(models.Model):
    _name = "ids.thing"
    _module = "test_ir_defaults_scope"
    _description = "thing"
    _log_access = False

    name = fields.Char()


def test_ir_defaults_is_superuser():
    with model_test_env(Thing) as env:
        assert env._ir_defaults._name == "ir.default"
        assert env._ir_defaults.env.uid == SUPERUSER_ID
        assert env._ir_defaults.env.su is True


def test_ir_defaults_is_memoized_per_environment():
    with model_test_env(Thing) as env:
        assert env._ir_defaults.env is env._ir_defaults.env
        other = env(context={"probe": 1})
        assert other._ir_defaults.env is not env._ir_defaults.env


def test_ir_defaults_escalates_a_non_superuser_environment():
    with model_test_env(Thing) as env:
        member = env["res.users"].create(
            {"name": "Member", "login": "member", "company_id": 1}
        )
        user_env = env(user=member.id, context={"allowed_company_ids": [1]})
        assert user_env.uid == member.id
        assert user_env.su is False

        assert user_env._ir_defaults.env.uid == SUPERUSER_ID
        assert user_env._ir_defaults.env.su is True


def test_ir_defaults_pins_the_company_even_when_the_context_omits_it():
    with model_test_env(Thing) as env:
        assert "allowed_company_ids" not in env.context

        resolved = env._ir_defaults.env
        assert resolved.context["allowed_company_ids"][0] == env.company.id


def test_ir_defaults_follows_a_context_selected_company():
    with model_test_env(Thing) as env:
        other = env["res.company"].create({"name": "Other"})
        scoped = env(context={"allowed_company_ids": [other.id, 1]})
        assert scoped.company.id == other.id

        assert scoped._ir_defaults.env.context["allowed_company_ids"][0] == other.id
