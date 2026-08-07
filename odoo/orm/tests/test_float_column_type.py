import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_float_column_type"


class FColumn(models.Model):
    _name = "f.column"
    _module = _MOD
    _description = "Float column type probe"

    plain = fields.Float()
    with_digits = fields.Float(digits=(16, 2))
    display_only = fields.Float(min_display_digits=2)


@pytest.fixture(scope="module")
def probe_fields():
    with model_test_env(FColumn) as env:
        yield env["f.column"]._fields


def test_plain_float_is_float8(probe_fields):
    field = probe_fields["plain"]
    assert field._digits is None
    assert field.column_type == ("float8", "double precision")


def test_explicit_digits_is_numeric(probe_fields):
    field = probe_fields["with_digits"]
    assert field._digits == (16, 2)
    assert field.column_type == ("numeric", "numeric")


def test_min_display_digits_selects_exact_numeric_storage(probe_fields):
    field = probe_fields["display_only"]
    assert field._digits is False, "the sentinel that selects exact storage"
    assert field.column_type == ("numeric", "numeric")
    assert field.get_digits(None) is False
