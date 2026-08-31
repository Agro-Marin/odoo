from odoo import fields, models

from odoo.addons.account.models.account_report import (
    FIGURE_TYPE_SELECTION_VALUES,
)


class AccountReportColumn(models.Model):
    _name = "account.report.column"
    _description = "Accounting Report Column"
    _order = "sequence, id"

    name = fields.Char(string="Name", translate=True, required=True)
    expression_label = fields.Char(string="Expression Label", required=True)
    sequence = fields.Integer(string="Sequence")
    report_id = fields.Many2one(
        string="Report",
        comodel_name="account.report",
        required=True,
        index="btree_not_null",
        ondelete="cascade",
    )
    sortable = fields.Boolean(string="Sortable")
    figure_type = fields.Selection(
        string="Figure Type",
        selection=FIGURE_TYPE_SELECTION_VALUES,
        default="monetary",
        required=True,
    )
    blank_if_zero = fields.Boolean(
        string="Blank if Zero",
        help="When checked, 0 values will not show in this column.",
    )
    custom_audit_action_id = fields.Many2one(
        string="Custom Audit Action", comodel_name="ir.actions.act_window"
    )
