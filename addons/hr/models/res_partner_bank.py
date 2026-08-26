from odoo import api, fields, models
from odoo.fields import Domain


class ResPartnerBank(models.Model):
    _inherit = "res.partner.bank"

    bank_street = fields.Char(related="bank_id.street", readonly=False)
    bank_street2 = fields.Char(related="bank_id.street2", readonly=False)
    bank_zip = fields.Char(related="bank_id.zip", readonly=False)
    bank_city = fields.Char(related="bank_id.city", readonly=False)
    bank_state = fields.Many2one(related="bank_id.state", readonly=False)
    bank_country = fields.Many2one(related="bank_id.country", readonly=False)
    bank_email = fields.Char(related="bank_id.email", readonly=False)
    bank_phone = fields.Char(related="bank_id.phone", readonly=False)
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        compute="_compute_employee_id",
        search="_search_employee_id",
    )
    employee_salary_amount = fields.Float(
        string="Salary Allocation",
        compute="_compute_salary_amount",
        digits=(16, 4),
        readonly=True,
        store=False,
    )
    employee_salary_amount_is_percentage = fields.Boolean(
        compute="_compute_salary_amount", readonly=True, store=False
    )
    currency_symbol = fields.Char(related="currency_id.symbol")
    employee_has_multiple_bank_accounts = fields.Boolean(
        related="employee_id.has_multiple_bank_accounts"
    )

    @api.depends("employee_id.salary_distribution")
    def _compute_salary_amount(self):
        for bank in self:
            distribution = bank.employee_id.salary_distribution or {}
            if str(bank.id) in distribution:
                # This account participates in the employee's distribution:
                # report its own allocated amount.
                (
                    bank.employee_salary_amount,
                    bank.employee_salary_amount_is_percentage,
                ) = bank.employee_id.get_bank_account_salary_allocation(bank.id)
                continue
            bank.employee_salary_amount_is_percentage = True
            if distribution:
                # Employee has a distribution but this account isn't in it yet:
                # show the still-allocatable percentage.
                bank.employee_salary_amount = (
                    bank.employee_id.get_remaining_percentage()
                )
            else:
                bank.employee_salary_amount = 0

    def _search_employee_id(self, operator, value):
        if operator not in ("in", "not in"):
            return NotImplemented
        # Two things the previous implementation got wrong, and one trap in
        # fixing it.
        #
        # 1. It searched ``hr.employee`` for ``id in value``, so the absent case
        #    (``employee_id = False`` -> ``("in", [False])``) matched no employee
        #    and returned NO accounts, where every non-employee account was
        #    wanted.
        # 2. It mapped matches through ``employee.bank_account_ids`` -- a
        #    different m2m from the ``work_contact_id`` o2m the compute reads --
        #    so an account sitting on an employee's work contact but absent from
        #    that m2m had ``employee_id`` set and was still never returned.
        #
        # The trap: this must NOT become a domain over
        # ``partner_id.employee_ids``. That field is hr.group_hr_user-only, so
        # the traversal raises AccessError for an ordinary internal user, while
        # ``employee_id`` itself carries no group and the compute resolves under
        # sudo. Resolve here under sudo too, through work_contact_id, scoped to
        # ``env.companies`` exactly as the compute is.
        Employee = self.env["hr.employee"].sudo()
        in_companies = Domain("company_id", "in", self.env.companies.ids)
        wanted_ids = [record_id for record_id in value if record_id]
        matched = Domain.FALSE
        if wanted_ids:
            partners = Employee.search(
                in_companies & Domain("id", "in", wanted_ids)
            ).work_contact_id
            matched |= Domain("partner_id", "in", partners.ids)
        if any(not record_id for record_id in value):
            employee_partners = Employee.search(in_companies).work_contact_id
            matched |= Domain("partner_id", "not in", employee_partners.ids)
        return matched if operator == "in" else ~matched

    def action_open_allocation_wizard(self):
        self.ensure_one()
        return self.employee_id.action_open_allocation_wizard()

    @api.depends("partner_id", "partner_id.employee_ids")
    def _compute_employee_id(self):
        for bank in self:
            # sudo: partner.employee_ids is gated behind hr.group_hr_user, but
            # ``employee_id`` itself carries no group, so it must compute for any
            # user who reads the bank account (mirrors _search_employee_id).
            partner = bank.partner_id.sudo()
            if partner.employee:
                bank.employee_id = partner.employee_ids.filtered(
                    lambda e: e.company_id in self.env.companies
                )[:1]
            else:
                bank.employee_id = False

    @staticmethod
    def _mask_account_number(acc_number):
        """Mask an employee bank account number for non-HR users.

        Reveals at most the last 4 characters, plus a 2-char prefix hint when the
        number is long enough (>= 7) for the middle to still be masked. NEVER falls
        through to the raw number: the base ``_compute_display_name`` renders the
        full ``acc_number``, so anything not masked here is fully exposed.

        The previous ``acc_number[:2] + "*" * len(acc_number[2:-4]) + acc_number[-4:]``
        slice broke for short numbers: length 6 produced zero stars (full number),
        and length 5 produced a corrupted, digit-duplicated string (``"12345"`` ->
        ``"122345"``). This form is correct for every length.
        """
        tail = acc_number[-4:]
        n = len(acc_number)
        if n <= 4:
            return "*" * n
        if n >= 7:
            return acc_number[:2] + "*" * (n - 6) + tail
        return "*" * (n - 4) + tail

    def _compute_display_name(self):
        account_employee = self.browse()
        if not self.env.user.has_group("hr.group_hr_user"):
            for account in self.sudo().filtered("partner_id.employee_ids"):
                acc_number = account.acc_number
                if not acc_number:
                    # Nothing to mask; let the base compute build the name.
                    continue
                account.sudo(self.env.su).display_name = self._mask_account_number(
                    acc_number
                )
                account_employee |= account
        super(ResPartnerBank, self - account_employee)._compute_display_name()
