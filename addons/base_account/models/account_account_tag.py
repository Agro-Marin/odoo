from odoo import fields, models


class AccountAccountTag(models.Model):
    """Tag for categorizing accounts, taxes, and products."""

    _name = "account.account.tag"
    _description = "Account Tag"

    name = fields.Char("Tag Name", required=True, translate=True)
    active = fields.Boolean(
        default=True,
        help="Set active to false to hide the Account Tag without removing it.",
    )
    color = fields.Integer("Color Index")
    applicability = fields.Selection(
        [("accounts", "Accounts"), ("taxes", "Taxes"), ("products", "Products")],
        required=True,
        default="accounts",
    )
    country_id = fields.Many2one(
        string="Country",
        comodel_name="res.country",
        help="Country for which this tag is available, when applied on taxes.",
    )

    _name_uniq = models.Constraint(
        "unique(name, applicability, country_id)",
        "A tag with the same name and applicability already exists in this country.",
    )
