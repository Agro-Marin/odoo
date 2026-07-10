import re
from typing import Any, Self

from odoo import api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import UserError
from odoo.tools import _, clean_context


def sanitize_account_number(acc_number: str | bool) -> str | bool:
    if acc_number:
        return re.sub(r"\W+", "", acc_number).upper()
    return False


class ResBank(models.Model):
    _name = "res.bank"
    _description = "Bank"
    _order = "name, id"
    _rec_names_search = ["name", "bic"]

    name = fields.Char(required=True)
    street = fields.Char()
    street2 = fields.Char()
    zip = fields.Char()
    city = fields.Char()
    state = fields.Many2one(
        "res.country.state",
        "Fed. State",
        domain="[('country_id', '=?', country)]",
    )
    country = fields.Many2one("res.country")
    country_code = fields.Char(related="country.code", string="Country Code")
    email = fields.Char()
    phone = fields.Char()
    active = fields.Boolean(default=True)
    bic = fields.Char(
        "Bank Identifier Code",
        index=True,
        help="Sometimes called BIC or Swift.",
    )

    @api.depends("name", "bic")
    def _compute_display_name(self) -> None:
        for bank in self:
            name = (bank.name or "") + ((bank.bic and (" - " + bank.bic)) or "")
            bank.display_name = name

    @api.model
    def _search_display_name(self, operator: str, value: str) -> list:
        if operator in ("ilike", "not ilike") and value:
            domain = [
                "|",
                ("bic", "=ilike", value + "%"),
                ("name", "ilike", value),
            ]
            if operator == "not ilike":
                domain = ["!", *domain]
            return domain
        return super()._search_display_name(operator, value)

    def _sanitize_vals(self, vals: ValuesType) -> ValuesType:
        if bic := vals.get("bic"):
            vals["bic"] = bic.upper()
        return vals

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        return super().create([self._sanitize_vals(vals) for vals in vals_list])

    def write(self, vals: dict[str, Any]) -> bool:
        return super().write(self._sanitize_vals(vals))

    @api.onchange("country")
    def _onchange_country_id(self) -> None:
        if self.country and self.country != self.state.country_id:
            self.state = False

    @api.onchange("state")
    def _onchange_state(self) -> None:
        if self.state.country_id:
            self.country = self.state.country_id


class ResPartnerBank(models.Model):
    _name = "res.partner.bank"
    _rec_name = "acc_number"
    _description = "Bank Accounts"
    _order = "sequence, id"
    _check_company_domain = models.check_company_domain_parent_of

    @api.model
    def _get_supported_account_types(self) -> list[tuple[str, str]]:
        return [("bank", _("Normal"))]

    active = fields.Boolean(default=True)
    acc_type = fields.Selection(
        selection=lambda x: x.env["res.partner.bank"]._get_supported_account_types(),
        compute="_compute_acc_type",
        string="Type",
        help="Bank account type: Normal or IBAN. Inferred from the bank account number.",
    )
    acc_number = fields.Char(
        "Account Number", required=True, search="_search_acc_number"
    )
    clearing_number = fields.Char("Clearing Number")
    sanitized_acc_number = fields.Char(
        compute="_compute_sanitized_acc_number",
        string="Sanitized Account Number",
        readonly=True,
        store=True,
    )
    acc_holder_name = fields.Char(
        string="Account Holder Name",
        help="Account holder name, in case it is different than the name of the Account Holder",
        compute="_compute_account_holder_name",
        readonly=False,
        store=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        "Account Holder",
        ondelete="cascade",
        index=True,
        domain=["|", ("is_company", "=", True), ("parent_id", "=", False)],
        required=True,
    )
    allow_out_payment = fields.Boolean(
        "Send Money",
        help="This account can be used for outgoing payments",
        default=False,
        copy=False,
        readonly=False,
    )
    bank_id = fields.Many2one("res.bank", string="Bank")
    bank_name = fields.Char(related="bank_id.name", readonly=False)
    bank_bic = fields.Char(related="bank_id.bic", readonly=False)
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one("res.currency", string="Currency")
    company_id = fields.Many2one(
        "res.company",
        "Company",
        related="partner_id.company_id",
        store=True,
        readonly=True,
    )
    country_code = fields.Char(related="partner_id.country_code", string="Country Code")
    note = fields.Text("Notes")
    color = fields.Integer(compute="_compute_color")

    _unique_number = models.Constraint(
        "unique(sanitized_acc_number, partner_id)",
        "The combination Account Number/Partner must be unique.",
    )

    @api.depends("acc_number")
    def _compute_sanitized_acc_number(self) -> None:
        for bank in self:
            bank.sanitized_acc_number = sanitize_account_number(bank.acc_number)

    def _search_acc_number(self, operator: str, value: str | list[str]) -> list:
        if operator in ("in", "not in"):
            value = [sanitize_account_number(i) for i in value]
        else:
            value = sanitize_account_number(value)
        return [("sanitized_acc_number", operator, value)]

    def _user_can_trust(self):
        self.ensure_one()
        return True

    def _find_or_create_bank_account(
        self,
        account_number,
        partner,
        company,
        *,
        allow_company_account_creation=False,
        extra_create_vals=None,
    ):
        """Find a bank account for ``partner`` and ``account_number``, creating it if absent.

        Handles two corner cases: the account may already exist restricted to
        another company (unique constraint), and accounts for the database's own
        companies are not created unless ``allow_company_account_creation``.

        :param account_number: account number to search for (or create)
        :param partner: partner linked to the account number
        :param company: company the account must be accessible from (search only)
        :param allow_company_account_creation: allow creating an account for our own companies
        :param extra_create_vals: values to set on create only, not written to a found account
        """
        bank_account = (
            self.env["res.partner.bank"]
            .sudo()
            .with_context(active_test=False)
            .search(
                [
                    ("acc_number", "=", account_number),
                    ("partner_id", "child_of", partner.commercial_partner_id.id),
                ]
            )
        )
        if not bank_account:
            if (
                not allow_company_account_creation
                and partner.id in self.env["res.company"]._get_company_partner_ids()
            ):
                raise UserError(
                    _(
                        "Please add your own bank account manually: %(account_number)s (%(partner)s)",
                        account_number=account_number,
                        partner=partner.display_name,
                    )
                )
            bank_account = (
                self.env["res.partner.bank"]
                .with_context(clean_context(self.env.context))
                .create(
                    {
                        **(extra_create_vals or {}),
                        "acc_number": account_number,
                        "partner_id": partner.id,
                        "allow_out_payment": False,
                    }
                )
            )
        return (
            bank_account.filtered_domain(
                [
                    *self.env["res.partner.bank"]._check_company_domain(company),
                    ("active", "=", True),
                ]
            )
            .sorted(lambda b: b.partner_id != partner)
            .sudo(False)[:1]
        )

    @api.depends("acc_number")
    def _compute_acc_type(self) -> None:
        for bank in self:
            bank.acc_type = self.retrieve_acc_type(bank.acc_number)

    @api.depends("partner_id")
    def _compute_account_holder_name(self) -> None:
        # Depends on partner_id only, NOT partner_id.name: acc_holder_name is a
        # user-editable default (store=True, readonly=False) meant to hold a
        # name different from the partner's. Depending on the name would clobber
        # customized holder names on every rename; renames are instead
        # propagated by a guarded sync in res.partner.write().
        for bank in self:
            bank.acc_holder_name = bank.partner_id.name

    @api.model
    def retrieve_acc_type(self, acc_number: str) -> str:
        """To be overridden by subclasses in order to support other account_types."""
        return "bank"

    @api.depends("acc_number", "bank_id.name")
    def _compute_display_name(self) -> None:
        for acc in self:
            # acc_number is required on persisted records but False on transient
            # NewId/onchange records; fall back to "" to keep display_name a string.
            acc_number = acc.acc_number or ""
            acc.display_name = (
                f"{acc_number} - {acc.bank_id.name}" if acc.bank_id else acc_number
            )

    @api.depends("allow_out_payment")
    def _compute_color(self) -> None:
        for bank in self:
            bank.color = 10 if bank.allow_out_payment else 1

    def _sanitize_vals(self, vals: ValuesType) -> ValuesType:
        if "acc_number" not in vals and "sanitized_acc_number" in vals:
            # Do not allow writing sanitized directly — treat it as acc_number
            vals["acc_number"] = vals.pop("sanitized_acc_number")
        if "acc_number" in vals:
            # acc_number is canonical: sanitized_acc_number is always derived
            # from it, overriding any sanitized value passed alongside.
            vals["sanitized_acc_number"] = sanitize_account_number(vals["acc_number"])
        return vals

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        return super().create([self._sanitize_vals(vals) for vals in vals_list])

    def write(self, vals: dict[str, Any]) -> bool:
        return super().write(self._sanitize_vals(vals))

    def action_archive_bank(self) -> dict[str, str]:
        """Archive the account and reload the client view."""
        # The plain action_archive does not trigger a re-rendering of the page,
        # so the archived record would stay visible; reload to refresh the view.
        self.ensure_one()
        self.action_archive()
        return {"type": "ir.actions.client", "tag": "reload"}

    def unlink(self) -> bool:
        """Archive instead of deleting; bank accounts may be linked to accounting entries."""
        # A real delete would orphan/RESTRICT entries referencing this account,
        # so we archive (active=False) and report success without calling super().
        self.action_archive()
        return True
