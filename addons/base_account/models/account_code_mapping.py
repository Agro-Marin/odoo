from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import Query

# A code-mapping record has no table of its own; its virtual id packs the pair
# (account_id, company_id) as ``account_id * COMPANY_OFFSET + company_id``.  For
# the pair to round-trip, ``company_id`` must stay strictly below the offset --
# otherwise it overflows into the account_id part and silently decodes to the
# wrong account *and* the wrong company.  10**6 comfortably clears any realistic
# ``res.company`` id (the previous 10**4 could be exceeded by a long-lived DB
# whose company sequence has climbed past 10k through creations + deletions).
COMPANY_OFFSET = 10**6


def _pack_mapping_id(account_id, company_id):
    """Encode an (account, company) pair into a virtual code-mapping id."""
    if not 0 <= company_id < COMPANY_OFFSET:
        raise ValueError(
            f"Company id {company_id} does not fit the code-mapping id encoding "
            f"(must be < {COMPANY_OFFSET})."
        )
    return account_id * COMPANY_OFFSET + company_id


class AccountCodeMapping(models.Model):
    """Virtual mapping of account codes per company.

    This model is used purely for UI, to display the account codes for
    each company in the account form.  It is not stored in DB.  Instead,
    records are populated in cache by the ``_search`` override when
    accessing the One2many on ``account.account``.
    """

    _name = "account.code.mapping"
    _description = "Mapping of account codes per company"
    _auto = False
    _table_query = "0"

    account_id = fields.Many2one(
        comodel_name="account.account",
        string="Account",
        compute="_compute_account_id",
        # suppress warning about field not being searchable (due to being
        # used in depends); searching is implemented in the _search override.
        search=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        compute="_compute_company_id",
    )
    code = fields.Char(
        string="Code",
        compute="_compute_code",
        inverse="_inverse_code",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Create virtual mappings by computing IDs from account+company.

        Deduplicates by ``(account_id, company_id)`` — when multiple commands
        target the same pair (e.g. from Form onchange + defaults), entries
        with a truthy ``code`` take precedence so that user-edited values are
        not overwritten by empty defaults.
        """
        by_key: dict[tuple[int, int], dict] = {}
        for vals in vals_list:
            key = (vals.get("account_id", 0), vals["company_id"])
            if key not in by_key or vals.get("code"):
                by_key[key] = vals
        vals_list = list(by_key.values())

        mappings = self.browse(
            [
                _pack_mapping_id(vals["account_id"], vals["company_id"])
                for vals in vals_list
            ]
        )
        for mapping, vals in zip(mappings, vals_list, strict=True):
            mapping.code = vals["code"]
        return mappings

    def _search(self, domain, offset=0, limit=None, order=None, **kw) -> Query:
        account_ids = []

        def get_accounts(condition):
            if (
                not account_ids
                and condition.field_expr == "account_id"
                and condition.operator == "in"
            ):
                account_ids.extend(condition.value)
                return Domain(bool(condition.value))
            return condition

        remaining_domain = Domain(domain).map_conditions(get_accounts)
        if not account_ids:
            raise UserError(
                _(
                    "Account Code Mapping cannot be accessed directly. "
                    "It is designed to be used only through the Chart of Accounts."
                )
            )
        return (
            self.browse(
                [
                    _pack_mapping_id(account_id, company.id)
                    for account_id in account_ids
                    for company in self.env.user.with_context(
                        active_test=True
                    ).company_ids.sorted(lambda c: (c.sequence, c.name))
                ]
            )
            .filtered_domain(remaining_domain)
            ._as_query()
        )

    def _compute_account_id(self):
        for record in self:
            record.account_id = record._origin.id // COMPANY_OFFSET

    def _compute_company_id(self):
        for record in self:
            record.company_id = record._origin.id % COMPANY_OFFSET

    @api.depends("account_id.code")
    def _compute_code(self):
        for record in self:
            account = record.account_id.with_company(record.company_id._origin)
            record.code = account.code

    def _inverse_code(self):
        for record in self:
            record.account_id.with_company(record.company_id).write(
                {"code": record.code}
            )
