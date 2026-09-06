from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command

EXPIRING_SOON_DAYS = 30


class DocumentDocument(models.Model):
    _inherit = "document.document"

    document_type_id = fields.Many2one(
        comodel_name="document.type",
        index=True,
        help="What kind of document this is. The type decides which attributes "
        "apply, starting with whether the document expires",
    )
    has_expiration = fields.Boolean(
        related="document_type_id.has_expiration",
    )
    legal_number = fields.Char(
        help="Official registration, license, or identification number for this document",
    )
    issuer_id = fields.Many2one(
        comodel_name="res.partner",
        help="The organization or government authority that issued this document",
    )
    date_issued = fields.Date(
        help="The date when this document was officially issued",
    )
    date_expiration = fields.Date(
        help="The date when this document expires",
    )
    days_left = fields.Integer(
        compute="_compute_days_left",
        help="Number of days remaining until document expires (0 for non-expiring documents)",
    )
    expiration_state = fields.Selection(
        selection=[
            ("valid", "Valid"),
            ("expiring_soon", "Expiring Soon"),
            ("expired", "Expired"),
            ("missing", "Missing"),
        ],
        compute="_compute_expiration_state",
        store=True,
        help="Where the document stands against its expiration date: Valid (more "
        "than 30 days left), Expiring Soon (30 days or fewer), Expired (past date), "
        "Missing (the type expires and no date is set). Empty when the type does "
        "not expire",
    )

    _legal_number_uniq = models.UniqueIndex(
        "(legal_number, document_type_id, company_id) NULLS NOT DISTINCT "
        "WHERE legal_number IS NOT NULL",
        "Legal number must be unique per document type and company!",
    )
    _date_expiration_idx = models.Index(
        "(date_expiration) WHERE date_expiration IS NOT NULL"
    )

    @api.model
    def _get_expiration_today(self, company=None) -> date:
        company = company or self.env.company
        tz = company.partner_id.tz
        return fields.Date.context_today(self.with_context(tz=tz) if tz else self)

    def _group_by_expiration_today(self):
        for company, records in self.grouped("company_id").items():
            yield self._get_expiration_today(company or None), records

    def _iter_expiration_windows(self):
        companies = self.env["res.company"].search([])
        for company in [*companies, self.env["res.company"]]:
            yield (
                self._get_expiration_today(company or None),
                [("company_id", "=", company.id or False)],
            )

    @api.constrains("document_type_id", "company_id")
    def _check_document_type_company(self) -> None:
        for record in self:
            type_company = record.document_type_id.company_id
            if type_company and record.company_id and type_company != record.company_id:
                raise ValidationError(
                    self.env._(
                        "Document '%(doc)s' belongs to %(doc_company)s but its type "
                        "'%(type)s' belongs to %(type_company)s.",
                        doc=record.name,
                        doc_company=record.company_id.name,
                        type=record.document_type_id.name,
                        type_company=type_company.name,
                    )
                )

    @api.depends("date_expiration", "company_id")
    def _compute_days_left(self) -> None:
        for today, records in self._group_by_expiration_today():
            for record in records:
                record.days_left = (
                    (record.date_expiration - today).days
                    if record.date_expiration
                    else 0
                )

    @api.depends("date_expiration", "company_id", "document_type_id.has_expiration")
    def _compute_expiration_state(self) -> None:
        for today, records in self._group_by_expiration_today():
            soon = today + timedelta(days=EXPIRING_SOON_DAYS)
            for record in records:
                if not record.document_type_id.has_expiration:
                    record.expiration_state = False
                elif not record.date_expiration:
                    record.expiration_state = "missing"
                elif record.date_expiration < today:
                    record.expiration_state = "expired"
                elif record.date_expiration <= soon:
                    record.expiration_state = "expiring_soon"
                else:
                    record.expiration_state = "valid"

    @api.onchange("document_type_id")
    def _onchange_document_type_id(self) -> None:
        doc_type = self.document_type_id
        if not doc_type:
            return
        if doc_type.folder_id:
            self.folder_id = doc_type.folder_id
        if doc_type.tag_ids:
            self.tag_ids = [Command.link(tag.id) for tag in doc_type.tag_ids]
        if not doc_type.has_expiration or not doc_type.default_validity_days:
            return
        if not self.date_issued:
            self.date_issued = fields.Date.context_today(self)
        if not self.date_expiration:
            self.date_expiration = self.date_issued + timedelta(
                days=doc_type.default_validity_days
            )

    @api.model
    def _cron_refresh_expiration_state(self) -> bool:
        stale = self.browse()
        for today, company_domain in self._iter_expiration_windows():
            stale |= self.search(
                [
                    *company_domain,
                    ("document_type_id.has_expiration", "=", True),
                    ("date_expiration", "!=", False),
                    "|",
                    "&",
                    ("date_expiration", "<", today),
                    ("expiration_state", "!=", "expired"),
                    "&",
                    "&",
                    ("date_expiration", ">=", today),
                    (
                        "date_expiration",
                        "<=",
                        today + timedelta(days=EXPIRING_SOON_DAYS),
                    ),
                    ("expiration_state", "=", "valid"),
                ]
            )
        if stale:
            stale._recompute_expiration_state()
        return True

    def _recompute_expiration_state(self) -> None:
        self.env.add_to_compute(self._fields["expiration_state"], self)
        self.flush_recordset(["expiration_state"])
