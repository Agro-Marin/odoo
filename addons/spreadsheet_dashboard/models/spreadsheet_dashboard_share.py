import base64
import uuid

from werkzeug.exceptions import Forbidden

from odoo import _, api, fields, models
from odoo.tools import consteq


class SpreadsheetDashboardShare(models.Model):
    _name = "spreadsheet.dashboard.share"
    _inherit = ["mixin.spreadsheet"]
    _description = "Copy of a shared dashboard"
    _order = "create_date desc"

    dashboard_id = fields.Many2one(
        "spreadsheet.dashboard", required=True, ondelete="cascade"
    )
    dashboard_group_id = fields.Many2one(related="dashboard_id.dashboard_group_id")
    excel_export = fields.Binary()
    active = fields.Boolean(default=True)
    access_token = fields.Char(required=True, default=lambda _x: str(uuid.uuid4()))
    full_url = fields.Char(string="URL", compute="_compute_full_url")
    name = fields.Char(
        compute="_compute_name",
        store=True,
        readonly=False,
        required=True,
        precompute=True,
        translate=True,
    )

    @api.depends("access_token")
    def _compute_full_url(self):
        for share in self:
            share.full_url = "%s/dashboard/share/%s/%s" % (
                share.get_base_url(),
                share.id,
                share.access_token,
            )

    @api.depends("dashboard_id")
    def _compute_name(self):
        # Reading ``share.name`` here is what makes the field editable: a name
        # the user gave, or one passed to ``create``, is never overwritten when
        # the dashboard is renamed.
        for share in self:
            if not share.name and share.dashboard_id:
                share.name = _("%s - Share Link", share.dashboard_id.name)

    @api.model
    def action_get_share_url(self, vals):
        if "excel_files" in vals:
            excel_zip = self._zip_xslx_files(vals["excel_files"])
            del vals["excel_files"]
            vals["excel_export"] = base64.b64encode(excel_zip)
        return self.create(vals).full_url

    def _check_token(self, access_token):
        if not access_token:
            return False
        return consteq(access_token, self.access_token)

    def _check_dashboard_access(self, access_token):
        self.check_singleton()
        token_access = self._check_token(access_token)
        dashboard = self.dashboard_id.with_user(self.create_uid)
        user_access = dashboard.has_access("read")
        if not (token_access and user_access):
            raise Forbidden(_("You don't have access to this dashboard. "))
