from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools import Query

# Must exceed any realistic res.company id: undersizing it silently decodes
# a packed id to the wrong account/company instead of raising.
COMPANY_OFFSET = 10**6


def _pack_mapping_id(account_id, company_id):
    if not 0 <= company_id < COMPANY_OFFSET:
        raise ValueError(
            f"Company id {company_id} does not fit the code-mapping id encoding "
            f"(must be < {COMPANY_OFFSET})."
        )
    return account_id * COMPANY_OFFSET + company_id


def _pinned_ids(domain):
    conjuncts = (
        domain.children if getattr(domain, "OPERATOR", None) == "&" else (domain,)
    )
    for condition in conjuncts:
        if (
            getattr(condition, "field_expr", None) == "id"
            and condition.operator == "in"
            and not isinstance(condition.value, Query)
        ):
            return condition.value
    return None


class AccountCodeMapping(models.Model):
    """Per-company code override for an account, keyed by a packed virtual id."""

    _name = "account.code.mapping"
    _description = "Mapping of account codes per company"
    _auto = False
    _table_query = "0"
    _search_visibility_fields = ()

    account_id = fields.Many2one(
        comodel_name="account.account",
        compute="_compute_account_id",
        search="_search_account_id",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        compute="_compute_company_id",
    )
    code = fields.Char(
        compute="_compute_code",
        inverse="_inverse_code",
    )

    @api.model_create_multi
    def create(self, vals_list):
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
        domain = Domain(domain).optimize_full(self)
        if (scope := _pinned_ids(domain)) is not None:
            company_ids = set(self._mapped_company_ids())
            mapping_ids = [
                id_ for id_ in scope if id_ and id_ % COMPANY_OFFSET in company_ids
            ]
        else:
            mapping_ids = self._mapping_ids(self.env["account.account"].search([]).ids)
        mappings = self.browse(mapping_ids).filtered_domain(domain)
        return mappings[offset:][:limit]._as_query()

    def _search_account_id(self, operator, value):
        if operator == "in":
            account_ids = [id_ for id_ in value if id_]
        elif operator in ("any", "any!"):
            accounts = self.env["account.account"].sudo(operator == "any!")
            if isinstance(value, Query):
                value = Domain("id", "in", value)
            account_ids = accounts.search(value).ids
        else:
            return NotImplemented
        return Domain("id", "in", self._mapping_ids(account_ids))

    def _mapping_ids(self, account_ids):
        company_ids = self._mapped_company_ids()
        return [
            _pack_mapping_id(account_id, company_id)
            for account_id in account_ids
            for company_id in company_ids
        ]

    def _mapped_company_ids(self):
        return (
            self.env.user.with_context(active_test=True)
            .company_ids.sorted(lambda c: (c.sequence, c.name))
            .ids
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
