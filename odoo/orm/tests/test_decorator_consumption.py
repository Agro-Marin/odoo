import logging

import pytest

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.orm.model_test_env import model_test_env

_MOD = "test_decorator_consumption"


def _amount_fields(model):
    assert model._name == "deccons.order"
    return ["amount", "amount_limit"]


class DecOrder(models.Model):
    _name = "deccons.order"
    _module = _MOD
    _description = "Decorator Consumption Order"

    name = fields.Char()
    amount = fields.Integer()
    amount_limit = fields.Integer(default=100)
    total = fields.Integer(compute="_compute_total", store=True)

    @api.constrains(_amount_fields)
    def _check_amount(self):
        for record in self:
            if record.amount > record.amount_limit:
                raise ValidationError(self.env._("amount must not exceed amount_limit"))

    @api.depends(lambda model: ("amount", "amount_limit"))
    def _compute_total(self):
        for record in self:
            record.total = record.amount + record.amount_limit


class DecSudoProbe(models.Model):
    _name = "deccons.probe"
    _module = _MOD
    _description = "Constraint Sudo Probe"

    name = fields.Char()

    observed_su = []

    @api.constrains("name")
    def _check_name_default_sudo(self):
        for record in self:
            type(self).observed_su.append(("default", record.env.su))

    @api.constrains("name", sudo=False)
    def _check_name_user_env(self):
        for record in self:
            type(self).observed_su.append(("user", record.env.su))


class DecBadSpec(models.Model):
    _name = "deccons.badspec"
    _module = "test_decorator_consumption_bad"
    _description = "Constraint With Unknown Field"

    name = fields.Char()

    @api.constrains("name", "no_such_field")
    def _check_unknown(self):
        pass


class TestConstrainsCallableConsumption:
    def test_callable_spec_resolves_and_registers_fields(self):
        with model_test_env(DecOrder) as env:
            methods = env["deccons.order"]._constraint_methods
            by_fields = {func._constrains: func for func in methods}
            assert ("amount", "amount_limit") in by_fields
            wrapped = by_fields[("amount", "amount_limit")]
            assert wrapped._constrains_sudo is True

    def test_constraint_fires_on_create_of_resolved_field(self):
        with model_test_env(DecOrder) as env:
            order_model = env["deccons.order"]
            record = order_model.create({"name": "ok", "amount": 5})
            assert record.amount == 5
            with pytest.raises(ValidationError, match="must not exceed"):
                order_model.create({"name": "boom", "amount": 500})

    def test_constraint_fires_on_write_of_resolved_field(self):
        with model_test_env(DecOrder) as env:
            record = env["deccons.order"].create({"name": "ok", "amount": 5})
            with pytest.raises(ValidationError, match="must not exceed"):
                record.write({"amount": 500})
                record.env.flush_all()


class TestDependsCallableConsumption:
    def test_callable_spec_feeds_the_dependency_graph(self):
        with model_test_env(DecOrder) as env:
            total = env["deccons.order"]._fields["total"]
            assert env.registry.field_depends[total] == ("amount", "amount_limit")

    def test_modifying_resolved_dependency_triggers_recompute(self):
        with model_test_env(DecOrder) as env:
            record = env["deccons.order"].create({"name": "x", "amount": 5})
            assert record.total == 105
            record.amount = 7
            assert record.total == 107
            record.amount_limit = 10
            assert record.total == 17


class TestConstraintSudoSemantics:
    def _validate_and_collect(self, records):
        DecSudoProbe.observed_su.clear()
        records._validate_fields(["name"])
        return dict(DecSudoProbe.observed_su)

    def test_superuser_env_runs_all_constraints_as_su(self):
        with model_test_env(DecSudoProbe) as env:
            record = env["deccons.probe"].create({"name": "a"})
            observed = self._validate_and_collect(record)
            assert observed == {"default": True, "user": True}

    def test_non_superuser_env_sudo_default_vs_sudo_false(self):
        with model_test_env(DecSudoProbe) as env:
            record = env["deccons.probe"].create({"name": "a"})
            user = env["res.users"].create(
                {"name": "User", "login": "user", "company_id": env.company.id}
            )
            user_env = env(user=user.id, su=False)
            assert user_env.su is False
            record_as_user = user_env["deccons.probe"].browse(record.id)

            observed = self._validate_and_collect(record_as_user)
            assert observed == {"default": True, "user": False}


class TestConstrainsUnknownFieldWarning:
    def test_unknown_field_name_logs_warning_but_registers(self, caplog):
        with model_test_env(DecBadSpec) as env:
            with caplog.at_level(logging.WARNING, logger="odoo.models"):
                methods = env["deccons.badspec"]._constraint_methods
        messages = [
            record.getMessage()
            for record in caplog.records
            if "@constrains parameter" in record.getMessage()
        ]
        assert len(messages) == 1, caplog.records
        assert "'no_such_field'" in messages[0]
        assert "is not a field name" in messages[0]
        assert any(func._constrains == ("name", "no_such_field") for func in methods)
