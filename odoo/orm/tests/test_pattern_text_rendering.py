"""``like``/``ilike`` renders a value the same way PostgreSQL's ``::text`` does.

A pattern operator on a non-text field compares against a *rendering* of the
value, and the two evaluators used to produce different ones:
``Field.condition_to_sql`` emits ``column::text`` while ``Field.filter_function``
used ``str(x) if x else ""``.  They disagreed in two ways, both reachable from
any RPC-supplied domain:

* a falsy-but-present value rendered as ``""`` -- ``('color', 'ilike', '0')``
  matched the record with ``color = 0`` under ``search()`` and nothing under
  ``filtered_domain()``;
* an integral float kept Python's ``.0`` -- ``('rounding', 'ilike', '1.0')``
  matched 8 records under ``filtered_domain()`` and none under ``search()``,
  because PostgreSQL prints a stored ``1.0`` as ``1``.

:meth:`Field._pattern_text` is now the single authority, so the two cannot
drift.  The rendering rules encoded here were verified against a live server
(``int4``, ``float8`` and scale-less ``numeric`` over integral, fractional,
negative-zero, ``1e20`` and ``1e-7`` values): zero mismatches.
"""

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
    """SQL ``NULL LIKE ...`` is never a match; ``""`` matches no surviving pattern."""
    with model_test_env(Thing) as env:
        flds = _fields_of(env)
        for fname in ("name", "count", "ratio", "priced", "when"):
            assert flds[fname]._pattern_text(None) == "", fname


def test_falsy_numeric_is_not_null():
    """A stored zero renders as ``0``, the way ``0::int4::text`` does.

    The ``if x else ""`` guard conflated "no value" with "falsy value", so a
    real zero became unmatchable.
    """
    with model_test_env(Thing) as env:
        flds = _fields_of(env)
        assert flds["count"]._pattern_text(0) == "0"
        assert flds["ratio"]._pattern_text(0.0) == "0"
        assert flds["priced"]._pattern_text(0.0) == "0"
        # a Char's empty string and its NULL both render empty, as in SQL
        assert flds["name"]._pattern_text("") == ""
        assert flds["name"]._pattern_text(False) == ""


def test_integral_floats_lose_the_python_dot_zero():
    """PostgreSQL prints a stored float in shortest round-trip form."""
    with model_test_env(Thing) as env:
        flds = _fields_of(env)
        for fname in ("ratio", "priced"):
            field = flds[fname]
            assert field._pattern_text(1.0) == "1", fname
            assert field._pattern_text(100.0) == "100", fname
            assert field._pattern_text(-1.0) == "-1", fname
            # fractional values are already identical to repr()
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
