from odoo import fields, models


class AccountFiscalPositionAccount(models.Model):
    _name = "account.fiscal.position.account"
    _description = "Accounts Mapping of Fiscal Position"
    _rec_name = "position_id"
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of

    position_id = fields.Many2one(
        "account.fiscal.position",
        string="Fiscal Position",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="position_id.company_id",
        store=True,
    )
    account_src_id = fields.Many2one(
        "account.account",
        string="Account on Product",
        check_company=True,
        required=True,
    )
    account_dest_id = fields.Many2one(
        "account.account",
        string="Account to Use Instead",
        check_company=True,
        required=True,
    )

    _account_src_dest_uniq = models.Constraint(
        "unique (position_id,account_src_id,account_dest_id)",
        "An account fiscal position could be defined only one time on same accounts.",
    )
