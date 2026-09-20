import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_company_dependent_flush_key"


class CdHolder(models.Model):
    _name = "cd.holder"
    _module = _MOD
    _description = "Company Dependent Flush Key Holder"

    plain = fields.Char(company_dependent=True)
    shifted = fields.Char(company_dependent=True, depends_context=("lang", "company"))
    day = fields.Date(company_dependent=True)


@pytest.fixture
def env():
    gen = model_test_env(CdHolder)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


def test_the_flushed_jsonb_is_keyed_by_company_wherever_company_sits(env):
    record = env["cd.holder"].create([{}])
    record.plain = "p"
    record.shifted = "s"
    env.flush_all()

    row = env.backend.storage.get_row("cd_holder", record.id)
    assert row["plain"] == {str(env.company.id): "p"}
    assert row["shifted"] == {str(env.company.id): "s"}, (
        f"flushed {row['shifted']!r}: the company-dependent column was keyed "
        f"by another context element, so reads keyed by company will miss it"
    )
    env.invalidate_all()
    assert record.plain == "p"
    assert record.shifted == "s"


def test_missing_company_uses_default_but_empty_string_remains_stored(env, monkeypatch):
    monkeypatch.setattr(
        type(env["ir.default"]),
        "_get_model_defaults",
        lambda self, model: {"plain": "fallback", "day": "2026-09-11"},
    )
    record = env["cd.holder"].create({"plain": "", "day": False})
    env.flush_all()
    env.invalidate_all()
    assert record.plain == ""
    assert record.day is False
    other = env["res.company"].create({"name": "Other"})
    assert record.with_company(other).plain == "fallback"
    assert str(record.with_company(other).day) == "2026-09-11"
