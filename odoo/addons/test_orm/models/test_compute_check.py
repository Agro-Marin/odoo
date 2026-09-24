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


class TestOrmComputeCheckHost(models.Model):
    _name = "test_orm.compute_check_host"
    _description = "Record whose flag reads a field whose check creates a line"

    name = fields.Char()
    code = fields.Char(compute="_compute_code", store=True)
    lines_made = fields.Boolean(compute="_compute_lines_made", store=True)
    line_ids = fields.One2many("test_orm.compute_check_line", "host_id")
    has_code = fields.Boolean(compute="_compute_has_code")

    @api.depends("name")
    def _compute_code(self):
        for record in self:
            record.code = record.name

    @api.depends("name")
    def _compute_lines_made(self):
        for record in self:
            if not record.line_ids:
                self.env["test_orm.compute_check_line"].create({"host_id": record.id})
            record.lines_made = True

    @api.depends("code", "line_ids")
    def _compute_has_code(self):
        for record in self:
            record.has_code = bool(record.code)

    @api.constrains("code")
    def _check_code_lines_made(self):
        for record in self:
            if record.code and not record.lines_made:
                raise ValidationError(self.env._("A code needs its lines."))


class TestOrmComputeCheckLine(models.Model):
    _name = "test_orm.compute_check_line"
    _description = "Line a host's compute creates"

    host_id = fields.Many2one("test_orm.compute_check_host", ondelete="cascade")
