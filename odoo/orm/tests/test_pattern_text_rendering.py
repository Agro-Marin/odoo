from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_pattern_text_rendering"


class Thing(models.Model):
    _name = "ptr.thing"
    _module = _MOD
    _description = "thing"
    _log_access = False

    name = fields.Char()
    count = fields.Integer()
    ratio = fields.Float()
    priced = fields.Float(digits=(12, 6))
    when = fields.Date()


def _fields_of(env):
    record = env["ptr.thing"].browse()
    return record._fields


def test_null_renders_as_empty_for_every_type():
    with model_test_env(Thing) as env:
        flds = _fields_of(env)
        for fname in ("name", "count", "ratio", "priced", "when"):
            assert flds[fname]._pattern_text(None) == "", fname


def test_falsy_numeric_is_not_null():
    with model_test_env(Thing) as env:
        flds = _fields_of(env)
        assert flds["count"]._pattern_text(0) == "0"
        assert flds["ratio"]._pattern_text(0.0) == "0"
        assert flds["priced"]._pattern_text(0.0) == "0"
        assert flds["name"]._pattern_text("") == ""
        assert flds["name"]._pattern_text(False) == ""


def test_integral_floats_lose_the_python_dot_zero():
    with model_test_env(Thing) as env:
        flds = _fields_of(env)
        for fname in ("ratio", "priced"):
            field = flds[fname]
            assert field._pattern_text(1.0) == "1", fname
            assert field._pattern_text(100.0) == "100", fname
            assert field._pattern_text(-1.0) == "-1", fname
            assert field._pattern_text(0.5) == "0.5", fname
            assert field._pattern_text(0.001) == "0.001", fname
            assert field._pattern_text(1e20) == "1e+20", fname
            assert field._pattern_text(1e-7) == "1e-07", fname


def test_integer_rendering_matches_str():
    with model_test_env(Thing) as env:
        field = _fields_of(env)["count"]
        for value in (0, 1, -1, 5, 1_000_000, 2**30):
            assert field._pattern_text(value) == str(value)


def test_textual_and_date_rendering_is_str():
    with model_test_env(Thing) as env:
        flds = _fields_of(env)
        assert flds["name"]._pattern_text("abc") == "abc"
        import datetime

        assert flds["when"]._pattern_text(datetime.date(2020, 1, 2)) == "2020-01-02"
