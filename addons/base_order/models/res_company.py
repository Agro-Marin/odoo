from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class ResCompany(models.Model):
    _inherit = "res.company"

    order_cycle_interval_number = fields.Integer(
        string="Order Cycle",
        default=3,
        help="How long a partner may go without ordering before it counts as "
        "having gone quiet. Ordering rhythms differ by company and by "
        "industry: a seasonal crop supplier may need twelve months where a "
        "convenience retailer needs one.",
    )
    order_cycle_interval_type = fields.Selection(
        selection=[
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
            ("years", "Years"),
        ],
        string="Order Cycle Unit",
        default="months",
        required=True,
    )

    @api.constrains("order_cycle_interval_number")
    def _check_order_cycle_interval_number(self):
        for company in self:
            if company.order_cycle_interval_number < 0:
                raise ValidationError(
                    _(
                        "The order cycle of %(company)s must be zero or more.",
                        company=company.display_name,
                    ),
                )

    def _get_order_cycle_cutoff_date(self):
        self.ensure_one()
        return fields.Date.today() - relativedelta(
            **{self.order_cycle_interval_type: self.order_cycle_interval_number},
        )
