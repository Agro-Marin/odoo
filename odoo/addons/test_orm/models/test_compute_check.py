from odoo import api, fields, models
from odoo.exceptions import ValidationError


class TestOrmComputeCheck(models.Model):
    _name = "test_orm.compute_check"
    _description = "Record whose compute reads a field whose constraint reads it back"

    name = fields.Char()
    code = fields.Char(compute="_compute_code", store=True)
    label = fields.Char(compute="_compute_label", store=True)

    @api.depends("name")
    def _compute_code(self):
        for record in self:
            record.code = record.label and (record.name or "").upper()

    @api.depends("name")
    def _compute_label(self):
        for record in self:
            record.label = record.name

    @api.constrains("label")
    def _check_label_has_code(self):
        for record in self:
            if record.label and not record.code:
                raise ValidationError(self.env._("A label needs a code."))
