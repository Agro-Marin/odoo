from odoo import fields, models


class ReportLayout(models.Model):
    _name = "report.layout"
    _description = "Report Layout"
    _order = "sequence, id"

    # RLAY-C1: explicit cascade — a layout without its template is useless, and the
    # implicit `set null` default contradicts required=True (would orphan the row).
    view_id = fields.Many2one(
        "ir.ui.view", "Document Template", required=True, ondelete="cascade"
    )
    image = fields.Char(string="Preview image src")
    pdf = fields.Char(string="Preview pdf src")

    sequence = fields.Integer(default=50)
    name = fields.Char()
