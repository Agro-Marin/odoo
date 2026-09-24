from odoo import api, fields, models


class TestOrmManualLinesHolder(models.Model):
    _name = "test_orm.manual_lines_holder"
    _description = "Counts the lines of whatever manual one2many it is given"

    name = fields.Char()
    line_count = fields.Integer(compute="_compute_line_count")

    @api.depends(
        lambda self: [
            name
            for name, field in self._fields.items()
            if field.type == "one2many" and field.manual
        ]
    )
    def _compute_line_count(self):
        for holder in self:
            holder.line_count = sum(
                len(holder[name])
                for name, field in holder._fields.items()
                if field.type == "one2many" and field.manual
            )
