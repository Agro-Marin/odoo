from typing import Self

from odoo import api, fields, models
from odoo.models import ValuesType


class ResCompany(models.Model):
    _inherit = "res.company"

    resource_calendar_ids = fields.One2many(
        "resource.calendar",
        "company_id",
        "Working Hours",
    )
    resource_calendar_id = fields.Many2one(
        "resource.calendar",
        "Default Working Hours",
        ondelete="restrict",
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        # A ``resource_calendar_id`` given in vals already exists (Many2one
        # values are never creation commands), so it may be a caller-supplied
        # shared/global calendar (``company_id=False`` on purpose -- see
        # ``resource_calendar_ids``' "Visible to all" use case). Snapshot
        # which ones pre-date this call *before* creating: only a calendar
        # that did not exist yet -- i.e. one ``_create_resource_calendar()``
        # is about to make below -- may still need its company_id backfilled.
        preexisting_calendar_ids = set(
            self.env["resource.calendar"]
            .sudo()
            .browse(
                {
                    vals["resource_calendar_id"]
                    for vals in vals_list
                    if vals.get("resource_calendar_id")
                }
            )
            .exists()
            .ids
        )
        companies = super().create(vals_list)
        companies_without_calendar = companies.filtered(
            lambda c: not c.resource_calendar_id
        )
        if companies_without_calendar:
            companies_without_calendar.sudo()._create_resource_calendar()
        # calendar created from form view: no company_id set because record was still not created
        for company in companies:
            calendar = company.resource_calendar_id
            if (
                calendar
                and not calendar.company_id
                and calendar.id not in preexisting_calendar_ids
            ):
                calendar.company_id = company.id
        return companies

    @api.model
    def _init_data_resource_calendar(self):
        self.search([("resource_calendar_id", "=", False)])._create_resource_calendar()

    def _create_resource_calendar(self) -> None:
        vals_list = [company._prepare_resource_calendar_values() for company in self]
        resource_calendars = self.env["resource.calendar"].create(vals_list)
        for company, calendar in zip(self, resource_calendars, strict=True):
            company.resource_calendar_id = calendar

    def _prepare_resource_calendar_values(self) -> ValuesType:
        self.check_singleton()
        return {
            "name": self.env._("Standard 40 hours/week"),
            "company_id": self.id,
        }
