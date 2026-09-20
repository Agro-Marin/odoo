import pytest

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_flush_check_coupled"


class CoupledLine(models.Model):
    _name = "coupled.line"
    _module = _MOD
    _description = "Flush Check Coupled Line"
    _log_access = False

    name = fields.Char()
    rank = fields.Integer()
    balance = fields.Integer()
    amount = fields.Integer(compute="_compute_amount", store=True)
    untouched = fields.Integer(compute="_compute_untouched", store=True)

    _check_same_sign = models.Constraint(
        "CHECK((balance <= 0 AND amount <= 0) OR (balance >= 0 AND amount >= 0))",
        "amount and balance must share a sign",
    )

    @api.depends("balance")
    def _compute_amount(self):
        for line in self:
            line.amount = line.balance

    @api.depends("balance")
    def _compute_untouched(self):
        for line in self:
            line.untouched = line.balance + 100


@pytest.fixture
def env():
    with model_test_env(CoupledLine) as env:
        yield env


def _pending(record, name):
    return record.env.is_to_compute(record._fields[name], record)


def test_couplings_are_read_off_check_constraints(env):
    coupled = env["coupled.line"]._get_check_coupled_fields()
    fields_ = env["coupled.line"]._fields

    assert coupled == {fields_["balance"]: (fields_["amount"],)}


def test_flush_for_an_unrelated_field_recomputes_the_check_partner(env):
    line = env["coupled.line"].create({"balance": -20, "rank": 1})
    env.flush_all()
    line.write({"balance": 10, "rank": 2})
    assert _pending(line, "amount")

    line.flush_model(["rank"])

    row = env.cr.storage.get_row(line._table, line.id)
    assert (row["balance"], row["amount"]) == (10, 10)
    assert not _pending(line, "amount")


def test_flush_stays_lazy_for_computed_fields_no_check_names(env):
    line = env["coupled.line"].create({"balance": -20, "rank": 1})
    env.flush_all()
    line.write({"balance": 10, "rank": 2})

    line.flush_model(["rank"])

    assert _pending(line, "untouched")
    assert env.cr.storage.get_row(line._table, line.id)["untouched"] == 80
