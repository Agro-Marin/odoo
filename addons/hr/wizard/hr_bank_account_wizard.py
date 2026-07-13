from odoo import Command, api, fields, models
from odoo.exceptions import ValidationError
from odoo.libs.numbers.float_utils import float_is_zero, float_round


class BankAccountAllocationWizard(models.TransientModel):
    _name = "hr.bank.account.allocation.wizard"
    _description = "Bank Account Allocation Wizard"

    employee_id = fields.Many2one("hr.employee", required=True)
    allocation_ids = fields.One2many(
        "hr.bank.account.allocation.wizard.line",
        "wizard_id",
        string="Allocations",
        readonly=False,
    )

    def _prepare_allocations_from_employee(self):
        self.ensure_one()
        wizard_lines = []
        distribution = self.employee_id.salary_distribution or {}
        for order, ba in enumerate(self.employee_id.bank_account_ids):
            dist_entry = distribution.get(str(ba.id))
            if dist_entry:
                amount = dist_entry.get("amount")
                is_percentage = dist_entry.get("amount_is_percentage")
                sequence = dist_entry.get("sequence")
            else:
                # A bank account may not yet be present in the salary
                # distribution (e.g. freshly added on the employee). Seed a
                # default, empty percentage line derived from the bank account
                # order instead of blocking the wizard from opening.
                amount = 0.0
                is_percentage = True
                sequence = order
            wizard_lines.append(
                Command.create(
                    {
                        "bank_account_id": ba.id,
                        "amount": amount,
                        "amount_type": "percentage" if is_percentage else "fixed",
                        "trusted": ba.allow_out_payment,
                        "sequence": sequence,
                    }
                )
            )
        self.write({"allocation_ids": wizard_lines})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for wizard in records:
            wizard._prepare_allocations_from_employee()
        return records

    def action_save(self):
        self.ensure_one()

        # Line amounts are captured at 2 decimals (the wizard-line ``amount``
        # field precision); the percentage total is checked at the same
        # precision. Note hr.employee._check_salary_distribution itself compares
        # at 4 digits, but here the inputs never carry more than 2.
        precision_digits = 2

        distribution = {}
        percentage_total = 0.0
        has_percentage = False
        seen_accounts = set()
        trust_by_account = {}

        # Validate everything first and only mutate persistent records (the
        # ``allow_out_payment`` trust flag, the employee's distribution) once all
        # checks have passed — otherwise a later validation failure would leave
        # early lines' trust flags written while the distribution is not saved.
        for line in self.allocation_ids:
            bank_account = line.bank_account_id
            if bank_account.id in seen_accounts:
                raise ValidationError(
                    self.env._(
                        "Bank account %s is allocated on several lines; each"
                        " bank account can only be used once.",
                        bank_account.display_name,
                    )
                )
            seen_accounts.add(bank_account.id)

            line_amount = float_round(
                line.amount,
                precision_digits=precision_digits,
                rounding_method="DOWN",
            )
            is_percentage = line.amount_type == "percentage"
            distribution[str(bank_account.id)] = {
                "amount": line_amount,
                "sequence": line.sequence,
                "amount_is_percentage": is_percentage,
            }
            if is_percentage:
                has_percentage = True
                percentage_total += line_amount
            trust_by_account[bank_account] = line.trusted

        if has_percentage:
            # Mirror hr.employee._check_salary_distribution: when percentage
            # lines are present they must total exactly 100%. Fixed-amount lines
            # are absolute allocations and legitimately coexist with them (see
            # hr.employee.get_accounts_with_fixed_allocations), so they are not
            # summed into this check.
            if not float_is_zero(
                percentage_total - 100.0, precision_digits=precision_digits
            ):
                raise ValidationError(
                    self.env._("Total percentage allocation must equal 100%.")
                )

        # Side effects, batched by value. NOTE: writing allow_out_payment with
        # sudo() bypasses the accounting "trusted account" control on
        # res.partner.bank; kept as-is (out of scope).
        trusted = self.env["res.partner.bank"]
        untrusted = self.env["res.partner.bank"]
        for account, is_trusted in trust_by_account.items():
            if is_trusted:
                trusted |= account
            else:
                untrusted |= account
        if trusted:
            trusted.sudo().write({"allow_out_payment": True})
        if untrusted:
            untrusted.sudo().write({"allow_out_payment": False})

        self.employee_id.salary_distribution = distribution
