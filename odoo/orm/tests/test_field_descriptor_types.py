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
        assert_type(_Probe.an_int, fields.Integer)
        assert_type(_Probe.a_char, fields.Char)
        assert_type(_Probe.a_m2o, fields.Many2one)
