# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta

from odoo import api, _, fields, models


class FleetVehicleLog(models.Model):
    _name = "fleet.vehicle.log"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Logs for vehicles"

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
    )
    vehicle_id = fields.Many2one(
        comodel_name="fleet.vehicle",
        string="Vehicle",
        required=True,
    )
    driver_id = fields.Many2one(
        related="vehicle_id.driver_id",
        string="Driver",
    )
    manager_id = fields.Many2one(
        related="vehicle_id.manager_id",
        string="Fleet Manager",
    )
    odometer_uom_id = fields.Many2one(
        related="vehicle_id.odometer_uom_id",
        string="Unit",
        readonly=True,
    )
    vendor_id = fields.Many2one(
        comodel_name="res.partner",
        string="Vendor",
    )
    product_category_id = fields.Many2one(
        comodel_name="product.category",
        string="Product Category",
        domain=lambda self: [('parent_id', '=', self.env.ref('fleet.product_category_vehicle_services').id)],
        ondelete="restrict",
        required=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        domain=[('vehicle_service', '=', True)],
        ondelete="restrict",
        required=True,
    )
    service_ids = fields.Many2many(
        comodel_name="product.product",
        string="Included Services",
        help="When the log is of type \"Contract\" here the included services can be specified"
    )
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [
            ("new", "New"),
            ("running", "Running"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        string="State",
        default="new",
        group_expand=True,
        tracking=True
    )
    date = fields.Date(
        default=fields.Date.context_today,
        help="Date when the cost has been executed",
    )
    date_start = fields.Date(
        string="Start Date",
        default=fields.Date.context_today,
        tracking=True,
        help="Date when the coverage of the contract begins",
    )
    date_end = fields.Date(
        string="Expiration Date",
        default=lambda self: self.compute_next_year_date(fields.Date.context_today(self)),
        tracking=True,
        help="Date when the coverage of the contract expirates "
             "(by default, one year after begin date)",
    )
    odometer = fields.Float(
        string="Odometer Value",
        # TODO improve logic for account.move.line to set odometer
        # or to inforce only on the view
        # required=True,
        help="Odometer measure of the vehicle at the moment of this log",
    )
    amount = fields.Monetary(
        string="Cost",
        tracking=True,
    )
    inv_ref = fields.Char("Vendor Reference")
    notes = fields.Text()
    days_left = fields.Integer(
        string="Warning Date",
        compute="_compute_days_left",
    )

    @api.depends("date_end")
    def _compute_days_left(self):
        today = fields.Date.from_string(fields.Date.today())
        for log in self:
            if log.date_end:
                renew_date = fields.Date.from_string(log.date_end)
                diff_time = (renew_date - today).days
                log.days_left = diff_time if diff_time > 0 else 0
            else:
                log.days_left = -1

    def compute_next_year_date(self, strdate):
        start_date = fields.Date.from_string(strdate)
        return fields.Date.to_string(start_date + relativedelta(years=1))
