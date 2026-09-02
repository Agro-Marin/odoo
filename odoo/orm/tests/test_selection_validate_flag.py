import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_selection_validate_flag"


class SelHolder(models.Model):
    _name = "sel.holder"
    _module = _MOD
    _description = "Selection Validate Flag Holder"

    checked = fields.Selection([("a", "A"), ("b", "B")])
    unchecked = fields.Selection([("a", "A"), ("b", "B")], validate=False)


@pytest.fixture
def env():
    gen = model_test_env(SelHolder)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


def test_a_validated_selection_rejects_an_unlisted_key_on_write(env):
    record = env["sel.holder"].create([{"checked": "a"}])
    with pytest.raises(ValueError, match="Wrong value"):
        record.checked = "zzz"


def test_validate_false_disables_validation_on_write_too(env):
    record = env["sel.holder"].create([{"unchecked": "a"}])
    record.unchecked = "zzz"
    assert record.unchecked == "zzz"
