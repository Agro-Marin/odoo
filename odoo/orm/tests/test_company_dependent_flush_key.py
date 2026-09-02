import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_company_dependent_flush_key"


class CdHolder(models.Model):
    _name = "cd.holder"
    _module = _MOD
    _description = "Company Dependent Flush Key Holder"

    plain = fields.Char(company_dependent=True)
    # an explicit depends_context that does not lead with "company": the cache
    # key is ordered by depends_context, so the flush must find the company
    # component by position, not assume index 0
    shifted = fields.Char(company_dependent=True, depends_context=("lang", "company"))


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
    assert row["plain"] == {env.company.id: "p"}
    assert row["shifted"] == {env.company.id: "s"}, (
        f"flushed {row['shifted']!r}: the company-dependent column was keyed "
        f"by another context element, so reads keyed by company will miss it"
    )
