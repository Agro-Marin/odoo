"""Type-level regression test for the ``Field.__get__`` descriptor overloads.

This module is **statically checked by mypy** (the ``py_typecheck`` gate runs
``mypy -p odoo.orm``) and is **never executed**: its entire body lives under
``TYPE_CHECKING``, so importing it at runtime registers no model and costs
nothing. There are no runtime assertions here on purpose — the assertions are
``typing.assert_type`` calls that the type checker verifies.

It guards the descriptor typing implemented in ``odoo/orm/fields/``: model
field access must resolve to a concrete value type, not ``Any``. If an
overload regresses (e.g. a scalar field's value access erases back to ``Any``,
or class access stops returning the field), one of the ``assert_type`` calls
below becomes an ``[assert-type]`` error and the gate reports the drift.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import assert_type

    from odoo import fields, models

    class _Probe(models.Model):
        _name = "test.field.descriptor.types"

        an_int = fields.Integer()
        a_float = fields.Float()
        a_bool = fields.Boolean()
        a_char = fields.Char()
        a_text = fields.Text()
        a_date = fields.Date()
        a_datetime = fields.Datetime()
        a_selection = fields.Selection([("a", "A")])
        a_binary = fields.Binary()
        a_image = fields.Image()
        a_m2o = fields.Many2one("res.partner")

    def _check_instance_access(rec: _Probe) -> None:
        """Instance access yields the field's value type, not ``Any``."""
        assert_type(rec.an_int, int)
        assert_type(rec.a_float, float)
        assert_type(rec.a_bool, bool)
        assert_type(rec.a_char, "str | Literal[False]")
        assert_type(rec.a_text, "str | Literal[False]")
        assert_type(rec.a_date, "datetime.date | Literal[False]")
        assert_type(rec.a_datetime, "datetime.datetime | Literal[False]")
        assert_type(rec.a_selection, "str | Literal[False]")
        assert_type(rec.a_binary, "bytes | Literal[False]")
        assert_type(rec.a_image, "bytes | Literal[False]")

    def _check_class_access() -> None:
        """Class access yields the field descriptor itself, not a value."""
        assert_type(_Probe.an_int, fields.Integer)
        assert_type(_Probe.a_char, fields.Char)
        assert_type(_Probe.a_m2o, fields.Many2one)
