import contextlib
import itertools
import re
from bisect import bisect_left
from collections import defaultdict

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.libs.debug_log import DebugLog
from odoo.tools import SQL, Query

ACCOUNT_REGEX = re.compile(r"(?:(\S*\d+\S*))?(.*)")
ACCOUNT_CODE_REGEX = re.compile(r"^[A-Za-z0-9.\-/]+$")
ACCOUNT_CODE_NUMBER_REGEX = re.compile(r"(.*?)(\d*)(\D*?)$")

_debug = DebugLog(__name__)


class AccountAccount(models.Model):
    _name = "account.account"
    _inherit = [
        "mixin.company.split",
        "mixin.mail.thread",
        "mixin.mail.activity",
    ]
    _description = "Account"
    _order = "code, placeholder_code"
    _check_company_auto = True
    _check_company_domain = models.check_companies_domain_parent_of

    name = fields.Char(
        string="Account Name",
        translate=True,
        index="trigram",
        required=True,
        tracking=True,
    )
    description = fields.Text(translate=True)
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Account Currency",
        tracking=True,
        help="Forces all journal items in this account to have a specific "
        "currency (i.e. bank journals). If no currency is set, entries "
        "can use any currency.",
    )
    company_currency_id = fields.Many2one(
        comodel_name="res.currency",
        compute="_compute_company_currency_id",
    )
    code = fields.Char(
        size=64,
        compute="_compute_code",
        inverse="_inverse_code",
        search="_search_code",
    )
    code_store = fields.Char(company_dependent=True)
    placeholder_code = fields.Char(
        string="Display code",
        compute="_compute_placeholder_code",
        search="_search_placeholder_code",
    )
    active = fields.Boolean(
        default=True,
        tracking=True,
    )
    account_type = fields.Selection(
        selection=[
            ("asset_receivable", "Receivable"),
            ("asset_cash", "Bank and Cash"),
            ("asset_current", "Current Assets"),
            ("asset_non_current", "Non-current Assets"),
            ("asset_prepayments", "Prepayments"),
            ("asset_fixed", "Fixed Assets"),
            ("liability_payable", "Payable"),
            ("liability_credit_card", "Credit Card"),
            ("liability_current", "Current Liabilities"),
            ("liability_non_current", "Non-current Liabilities"),
            ("equity", "Equity"),
            ("equity_unaffected", "Current Year Earnings"),
            ("income", "Income"),
            ("income_other", "Other Income"),
            ("expense", "Expenses"),
            ("expense_other", "Other Expenses"),
            ("expense_depreciation", "Depreciation"),
            ("expense_direct_cost", "Cost of Revenue"),
            ("off_balance", "Off-Balance Sheet"),
        ],
        string="Type",
        compute="_compute_account_type_and_tags",
        precompute=True,
        store=True,
        index=True,
        readonly=False,
        required=True,
        tracking=True,
        help="Account Type is used for information purpose, to generate "
        "country-specific legal reports, and set the rules to close a "
        "fiscal year and generate opening entries.",
    )
    include_initial_balance = fields.Boolean(
        string="Bring Accounts Balance Forward",
        compute="_compute_include_initial_balance",
        search="_search_include_initial_balance",
        help="Used in reports to know if we should consider journal items "
        "from the beginning of time instead of from the fiscal year "
        "only. Account types that should be reset to zero at each new "
        "fiscal year (like expenses, revenue..) should not have this "
        "option set.",
    )
    internal_group = fields.Selection(
        selection=[
            ("equity", "Equity"),
            ("asset", "Asset"),
            ("liability", "Liability"),
            ("income", "Income"),
            ("expense", "Expense"),
            ("off", "Off Balance"),
        ],
        compute="_compute_internal_group",
        search="_search_internal_group",
    )
    reconcile = fields.Boolean(
        string="Allow Reconciliation",
        compute="_compute_reconcile",
        precompute=True,
        store=True,
        readonly=False,
        tracking=True,
        help="Check this box if this account allows invoices & payments "
        "matching of journal items.",
    )
    note = fields.Text(
        string="Internal Notes",
        tracking=True,
    )
    company_ids = fields.Many2many(
        comodel_name="res.company",
        string="Companies",
        depends_context=("uid",),
        default=lambda self: self.env.company,
        readonly=False,
        required=True,
    )
    code_mapping_ids = fields.One2many(
        comodel_name="account.code.mapping",
        inverse_name="account_id",
    )
    # Write after company_ids so _check_code_is_unique does not fire before
    # both fields are set together.
    code_mapping_ids.write_sequence = 19
    tag_ids = fields.Many2many(
        comodel_name="account.account.tag",
        relation="account_account_account_tag",
        string="Tags",
        compute="_compute_account_type_and_tags",
        precompute=True,
        store=True,
        readonly=False,
        ondelete="restrict",
        tracking=True,
        help="Optional tags you may want to assign for custom reporting",
    )
    root_id = fields.Many2one(
        comodel_name="account.root",
        compute="_compute_account_root",
        search="_search_account_root",
    )
    non_trade = fields.Boolean(
        default=False,
        help="If set, this account will belong to Non Trade "
        "Receivable/Payable in reports and filters.\n"
        "If not, this account will belong to Trade "
        "Receivable/Payable in reports and filters.",
    )
    display_mapping_tab = fields.Boolean(
        default=lambda self: len(self.env.user.company_ids) > 1,
        store=False,
    )

    company_fiscal_country_code = fields.Char(
        compute="_compute_company_fiscal_country_code"
    )
    tax_ids = fields.Many2many(
        comodel_name="account.tax",
        relation="account_account_tax_default_rel",
        column1="account_id",
        column2="tax_id",
        string="Default Taxes",
        context={"append_fields": ["type_tax_use", "company_ids"]},
        check_company=True,
    )
    group_id = fields.Many2one(
        comodel_name="account.group",
        compute="_compute_group_id",
        help="Account prefixes can determine account groups.",
    )
    used = fields.Boolean(
        compute="_compute_used",
        search="_search_used",
    )
    opening_debit = fields.Monetary(
        currency_field="company_currency_id",
        compute="_compute_opening_debit_credit",
        inverse="_inverse_opening_debit",
    )
    opening_credit = fields.Monetary(
        currency_field="company_currency_id",
        compute="_compute_opening_debit_credit",
        inverse="_inverse_opening_credit",
    )
    opening_balance = fields.Monetary(
        currency_field="company_currency_id",
        compute="_compute_opening_debit_credit",
        inverse="_inverse_opening_balance",
    )
    current_balance = fields.Float(compute="_compute_current_balance")
    related_taxes_amount = fields.Integer(compute="_compute_related_taxes_amount")

    def _field_to_sql(
        self, alias: str, field_expr: str, query: Query | None = None
    ) -> SQL:
        if field_expr == "internal_group":
            return SQL(
                "split_part(%s, '_', 1)",
                self._field_to_sql(alias, "account_type", query),
            )
        if field_expr == "code":
            return SQL(
                "(COALESCE(%(code_store)s->%(root_company_id)s, to_jsonb(NULL::varchar))->>0)::varchar",
                code_store=SQL.identifier(
                    alias, "code_store", to_flush=self._fields["code_store"]
                ),
                # Inlined as a literal, not a bound parameter: two bound
                # parameters would be distinct nodes to Postgres, breaking
                # ORDER BY/GROUP BY matching against this expression elsewhere.
                root_company_id=SQL(f"'{int(self.env.company.root_id.id)}'"),
            )
        if field_expr == "placeholder_code":
            if "account_first_company" not in query._joins:
                query.add_join(
                    "LEFT JOIN",
                    "account_first_company",
                    SQL(
                        """(
                            SELECT DISTINCT ON (rel.account_account_id)
                                rel.account_account_id AS account_id,
                                rel.res_company_id AS company_id,
                                SPLIT_PART(res_company.parent_path, '/', 1)
                                    AS root_company_id,
                                res_partner.name AS company_name
                            FROM account_account_res_company_rel rel
                            JOIN res_company
                                ON res_company.id = rel.res_company_id
                            JOIN res_partner
                                ON res_partner.id = res_company.partner_id
                            WHERE rel.res_company_id
                                IN %(authorized_company_ids)s
                        ORDER BY rel.account_account_id, company_id
                        )""",
                        authorized_company_ids=self.env.user._get_company_ids(),
                        to_flush=self._fields["company_ids"],
                    ),
                    SQL(
                        "account_first_company.account_id = %(account_id)s",
                        account_id=SQL.identifier(alias, "id"),
                    ),
                )

            return SQL(
                """
                    COALESCE(
                        %(code_store)s->>%(active_company_root_id)s,
                        %(code_store)s->>%(account_first_company_root_id)s
                            || ' (' || %(account_first_company_name)s || ')'
                    )
                """,
                code_store=SQL.identifier(alias, "code_store"),
                # Same literal-vs-bound-parameter requirement as the "code"
                # branch above.
                active_company_root_id=SQL(f"'{int(self.env.company.root_id.id)}'"),
                account_first_company_name=SQL.identifier(
                    "account_first_company",
                    "company_name",
                ),
                account_first_company_root_id=SQL.identifier(
                    "account_first_company",
                    "root_company_id",
                ),
                to_flush=self._fields["code_store"],
            )
        if field_expr == "root_id":
            return SQL(
                "SUBSTRING(%(placeholder_code)s, 1, 2)",
                placeholder_code=self._field_to_sql(
                    alias,
                    "placeholder_code",
                    query,
                ),
            )

        return super()._field_to_sql(alias, field_expr, query)

    @api.constrains("account_type", "reconcile")
    def _check_reconcile(self):
        for account in self:
            if (
                account.account_type in ("asset_receivable", "liability_payable")
                and not account.reconcile
            ):
                raise ValidationError(
                    self.env._(
                        "You cannot have a receivable/payable account that is "
                        "not reconcilable. (account code: %s)",
                        account.code,
                    )
                )

    @api.constrains("code")
    def _check_account_code(self):
        for account in self:
            if account.code and not ACCOUNT_CODE_REGEX.match(account.code):
                raise ValidationError(
                    self.env._(
                        "The account code can only contain alphanumeric "
                        "characters, dots, hyphens, and slashes.",
                    )
                )

    @api.constrains("company_ids", "account_type")
    def _check_company_consistency(self):
        self.invalidate_recordset(fnames=["company_ids"])
        if accounts_without_company := self.filtered(
            lambda a: not a.sudo().company_ids
        ):
            raise ValidationError(
                self.env._(
                    "The following accounts must be assigned to at least "
                    "one company:\n%(accounts)s",
                    accounts="\n".join(
                        f"- {account.display_name}"
                        for account in accounts_without_company
                    ),
                ),
            )
        if self.filtered(
            lambda a: a.account_type == "asset_cash" and len(a.company_ids) > 1
        ):
            raise ValidationError(
                self.env._("Bank & Cash accounts cannot be shared between companies."),
            )

    @api.depends_context("company")
    @api.depends("code_store")
    def _compute_code(self):
        for record, record_root in zip(
            self,
            self.with_company(self.env.company.root_id).sudo(),
            strict=True,
        ):
            record.code = record_root.code_store

    def _search_code(self, operator, value):
        return [
            (
                "id",
                "in",
                self.with_company(self.env.company.root_id)
                .with_context(active_test=False)
                .sudo()
                ._search([("code_store", operator, value)]),
            ),
        ]

    def _inverse_code(self):
        for record, record_root in zip(
            self,
            self.with_company(self.env.company.root_id).sudo(),
            strict=True,
        ):
            record_root.code_store = record.code

        self.invalidate_recordset(fnames=["code"], flush=False)
        self._compute_code()

    @api.depends_context("company", "uid")
    @api.depends("code")
    def _compute_placeholder_code(self):
        self.placeholder_code = False
        for record in self:
            if record.code:
                record.placeholder_code = record.code
            elif authorized_companies := (
                record.company_ids
                & self.env["res.company"].browse(
                    self.env.user._get_company_ids(),
                )
            ).sorted("id"):
                company = authorized_companies[0]
                if code := record.with_company(company).code:
                    record.placeholder_code = f"{code} ({company.name})"

    def _search_placeholder_code(self, operator, value):
        if operator not in ("=ilike", "in"):
            return NotImplemented
        query = Query(self.env, "account_account")
        placeholder_code_sql = self.env["account.account"]._field_to_sql(
            "account_account",
            "placeholder_code",
            query,
        )
        if operator == "in":
            query.add_where(
                SQL("%s = ANY(%s)", placeholder_code_sql, list(value)),
            )
        else:
            query.add_where(
                SQL("%s ILIKE %s", placeholder_code_sql, value),
            )
        return [("id", "in", query)]

    @api.depends_context("company")
    @api.depends("code")
    def _compute_account_root(self):
        for record in self:
            record.root_id = self.env["account.root"]._from_account_code(
                record.placeholder_code,
            )

    def _search_account_root(self, operator, value):
        if operator not in ("in", "child_of", "any"):
            return NotImplemented
        if operator == "any":
            if (
                isinstance(value, Domain)
                and value.field_expr == "display_name"
                and value.operator == "in"
            ):
                roots = self.env["account.root"].browse(value.value)
            else:
                return NotImplemented
        else:
            roots = self.env["account.root"].browse(value)
        return Domain.OR(
            Domain(
                "placeholder_code",
                "=ilike",
                root.name
                + ("" if operator in ["in", "any"] and not root.parent_id else "%"),
            )
            for root in roots
        )

    def _search_panel_get_domain_image(
        self,
        field_name,
        domain,
        set_count=False,
        limit=False,
    ):
        if field_name != "root_id" or set_count:
            return super()._search_panel_get_domain_image(
                field_name,
                domain,
                set_count,
                limit,
            )

        domain = Domain(domain)
        if domain.is_false():
            return {}

        query_account = self.env["account.account"]._search(
            domain,
            limit=limit,
        )
        placeholder_code_alias = self.env["account.account"]._field_to_sql(
            "account_account",
            "code",
            query_account,
        )

        placeholder_codes = self.env.execute_query(
            query_account.select(placeholder_code_alias),
        )
        return {
            (root := self.env["account.root"]._from_account_code(code)).id: {
                "id": root.id,
                "display_name": root.display_name,
            }
            for (code,) in placeholder_codes
            if code
        }

    @api.depends("code")
    def _compute_account_type_and_tags(self):
        accounts_to_process = self.filtered(
            lambda account: (
                account.code and (not account.account_type or not account.tag_ids)
            ),
        )
        self._update_from_closest_parent_account(
            accounts_to_process,
            {"account_type": "asset_current", "tag_ids": []},
        )

    def _update_from_closest_parent_account(self, accounts_to_process, field_defaults):
        field_names = list(field_defaults)
        assert all(field_name in self._fields for field_name in field_names)

        all_accounts = self.search_read(
            domain=self._check_company_domain(self.env.company),
            fields=["code", *field_names],
            order="code",
        )
        accounts_with_values = {}
        for account in all_accounts:
            accounts_with_values[account["code"]] = {
                field_name: account[field_name] for field_name in field_names
            }
        codes_list = list(accounts_with_values.keys())
        for account in accounts_to_process:
            closest_index = bisect_left(codes_list, account.code) - 1
            parent_values = (
                accounts_with_values[codes_list[closest_index]]
                if closest_index != -1
                else None
            )
            for field_name, default_value in field_defaults.items():
                if account[field_name]:
                    continue
                account[field_name] = (
                    parent_values[field_name] if parent_values else default_value
                )

    @api.depends("account_type")
    def _compute_include_initial_balance(self):
        for account in self:
            account.include_initial_balance = (
                account.internal_group not in ["income", "expense"]
                and account.account_type != "equity_unaffected"
            )

    def _search_include_initial_balance(self, operator, value):
        if operator != "in":
            return NotImplemented
        return [
            ("internal_group", "not in", ["income", "expense"]),
            ("account_type", "!=", "equity_unaffected"),
        ]

    def _get_internal_group(self, account_type):
        return account_type.split("_", maxsplit=1)[0]

    @api.depends("account_type")
    def _compute_internal_group(self):
        for account in self:
            account.internal_group = (
                account.account_type
                and account._get_internal_group(account.account_type)
            )

    def _search_internal_group(self, operator, value):
        if operator != "in":
            return NotImplemented
        return Domain.OR(
            Domain("account_type", "=like", self._get_internal_group(v) + "%")
            for v in value
        )

    @api.depends("account_type")
    def _compute_reconcile(self):
        for account in self:
            if account.internal_group in ("income", "expense", "equity"):
                account.reconcile = False
            elif account.account_type in (
                "asset_receivable",
                "liability_payable",
            ):
                account.reconcile = True
            elif account.account_type in (
                "asset_cash",
                "liability_credit_card",
                "off_balance",
            ):
                account.reconcile = False

    @api.depends_context("company")
    def _compute_company_currency_id(self):
        self.company_currency_id = self.env.company.currency_id

    @api.onchange("name")
    def _onchange_name(self):
        code, name = self._split_code_name(self.name)
        if code and not self.code:
            self.name = name
            self.code = code

    def _split_code_name(self, code_name):
        code, name = ACCOUNT_REGEX.match(code_name or "").groups()
        return code, name.strip()

    @api.model
    def _search_display_name(self, operator, value):
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        if operator == "in":
            return [
                "|",
                ("code", "in", [(name or "").split(" ")[0] for name in value]),
                ("name", "in", value),
            ]
        if isinstance(value, str):
            name = value or ""
            return [
                "|",
                "|",
                ("code", "=like", name.split(" ")[0] + "%"),
                ("name", operator, name),
                ("description", "ilike", name),
            ]
        return NotImplemented

    @api.model
    def _search_new_account_code(self, start_code, cache=None):
        if cache is None:
            cache = {start_code}

        company_domain = [
            "|",
            ("company_ids", "parent_of", self.env.company.id),
            ("company_ids", "child_of", self.env.company.id),
        ]

        def code_is_available(new_code):
            return new_code not in cache and not self.with_context(
                active_test=False
            ).sudo().search_count(
                [("code", "=", new_code), *company_domain],
                limit=1,
            )

        if code_is_available(start_code):
            return start_code

        start_str, digits_str, end_str = ACCOUNT_CODE_NUMBER_REGEX.match(
            start_code
        ).groups()

        if digits_str != "":
            d, n = len(digits_str), int(digits_str)
            code_len = len(start_str) + d + len(end_str)
            existing_codes = (
                self.with_context(active_test=False)
                .sudo()
                .search_read(company_domain, fields=["code"])
            )
            occupied = set()
            for existing in existing_codes:
                code = existing["code"]
                if (
                    code
                    and len(code) == code_len
                    and code.startswith(start_str)
                    and code.endswith(end_str)
                ):
                    middle = code[len(start_str) : code_len - len(end_str)]
                    if middle.isdigit():
                        occupied.add(int(middle))
            for num in range(n + 1, 10**d):
                if num in occupied:
                    continue
                new_code = f"{start_str}{num:0{d}}{end_str}"
                if new_code not in cache:
                    return new_code

        for num in range(99):
            if code_is_available(
                new_code := f"{start_code}.copy{(num and num + 1) or ''}"
            ):
                return new_code

        raise UserError(self.env._("Cannot generate an unused account code."))

    @api.model
    def default_get(self, fields):
        context = {}
        if "name" in fields or "code" in fields:
            default_name = self.env.context.get("default_name")
            default_code = self.env.context.get("default_code")
            if default_name and not default_code:
                is_numeric_code = False
                with contextlib.suppress(ValueError):
                    is_numeric_code = bool(int(default_name))
                if is_numeric_code:
                    context.update(
                        {
                            "default_name": False,
                            "default_code": default_name,
                        }
                    )

        defaults = super(
            AccountAccount,
            self.with_context(**context),
        ).default_get(fields)

        if "code_mapping_ids" in fields and "code_mapping_ids" not in defaults:
            defaults["code_mapping_ids"] = [
                Command.create({"company_id": c.id}) for c in self.env.user.company_ids
            ]

        return defaults

    @api.model
    def name_create(self, name):
        if "import_file" in self.env.context:
            code, name = self._split_code_name(name)
            record = self.create({"code": code, "name": name})
            return record.id, record.display_name
        raise ValidationError(
            self.env._("Please create new accounts from the Chart of Accounts menu."),
        )

    def _sort_vals_for_company_grouping(self, vals_list):
        first_seen = {}
        for index, vals in enumerate(vals_list):
            first_seen.setdefault(repr(vals.get("company_ids", [])), index)
        return sorted(
            vals_list,
            key=lambda vals: first_seen[repr(vals.get("company_ids", []))],
        )

    def _update_vals_with_code(self, vals, companies, cache):
        if "prefix" in vals:
            prefix = vals.pop("prefix") or ""
            digits = vals.pop("code_digits")
            start_code = (
                prefix.ljust(digits - 1, "0") + "1" if len(prefix) < digits else prefix
            )
            vals["code"] = self.with_company(
                companies[0],
            )._search_new_account_code(start_code, cache)
            cache.add(vals["code"])

        if "code" not in vals:
            for mapping_command in vals.get("code_mapping_ids", []):
                match mapping_command:
                    case (
                        Command.CREATE,
                        _,
                        {
                            "company_id": company_id,
                            "code": code,
                        },
                    ) if company_id == companies[0].id:
                        vals["code"] = code
                        break

    @api.model_create_multi
    def create(self, vals_list):
        records_list = []
        vals_list = self._sort_vals_for_company_grouping(vals_list)

        for company_ids, vals_list_for_company in itertools.groupby(
            vals_list,
            lambda v: v.get("company_ids", []),
        ):
            cache = set()
            vals_list_for_company = list(vals_list_for_company)

            company_ids = self._fields["company_ids"].convert_to_cache(
                company_ids,
                self.browse(),
            )
            companies = self.env["res.company"].browse(company_ids)
            if self.env.company in companies or not companies:
                companies = self.env.company | companies

            for vals in vals_list_for_company:
                self._update_vals_with_code(vals, companies, cache)

            new_accounts = super(
                AccountAccount,
                self.with_context(
                    allowed_company_ids=companies.ids,
                    defer_account_code_checks=True,
                    default_code_mapping_ids=self.env.context.get(
                        "default_code_mapping_ids",
                        [],
                    ),
                ),
            ).create(vals_list_for_company)

            records_list.append(new_accounts)

        records = self.env["account.account"].union(*records_list)
        records.flush_recordset()
        records.invalidate_recordset(fnames=["code", "code_store"])
        records._check_code_is_unique()
        return records

    def _check_code_is_unique(self):
        for account in self.sudo():
            for company in account.company_ids.root_id:
                acc_co = account.with_company(company)
                code = acc_co.code
                if not code:
                    raise ValidationError(
                        self.env._(
                            "The code must be set for every company to which "
                            "this account belongs.",
                        )
                    )

        account_ids_to_check_by_company = defaultdict(list)
        for account in self.sudo():
            for company in account.company_ids:
                account_ids_to_check_by_company[company].append(account.id)

        for company, account_ids in account_ids_to_check_by_company.items():
            accounts = self.browse(account_ids).with_prefetch(self.ids).sudo()

            accounts_by_code = accounts.with_company(company).grouped("code")
            duplicate_codes = None
            if len(accounts_by_code) < len(accounts):
                duplicate_codes = [
                    code for code, accs in accounts_by_code.items() if len(accs) > 1
                ]

            # One query per company, not per record: `code` is company-dependent
            # and is searched under that company's context, which a single
            # query over every company cannot express.
            elif duplicates := (
                self.with_company(company)
                .sudo()
                .with_context(active_test=False)
                .search_fetch(  # pylint: disable=n-plus-one-query
                    [
                        ("code", "in", list(accounts_by_code)),
                        ("id", "not in", self.ids),
                        "|",
                        ("company_ids", "parent_of", company.ids),
                        ("company_ids", "child_of", company.ids),
                    ],
                    ["code_store"],
                )
            ):
                duplicate_codes = duplicates.mapped("code")
            if duplicate_codes:
                raise ValidationError(
                    self.env._(
                        "Account codes must be unique. You can't create "
                        "accounts with these duplicate codes: %s",
                        ", ".join(duplicate_codes),
                    )
                )

    def _load_records_write(self, values):
        if "prefix" in values:
            del values["code_digits"]
            del values["prefix"]
        super()._load_records_write(values)

    def copy_data(self, default=None):
        vals_list = super().copy_data(default)
        default = default or {}
        cache = defaultdict(set)

        for account, vals in zip(self, vals_list, strict=True):
            company_ids = self._fields["company_ids"].convert_to_cache(
                vals["company_ids"],
                self.browse(),
            )
            companies = self.env["res.company"].browse(company_ids)

            if "code_mapping_ids" not in default and (
                "code" not in default or len(companies) > 1
            ):
                companies_to_get_new_codes = (
                    companies if "code" not in default else companies[1:]
                )
                vals["code_mapping_ids"] = []

                for company in companies_to_get_new_codes:
                    start_code = (
                        account.with_company(company).code
                        or account.with_company(
                            account.company_ids[0],
                        ).code
                    )
                    new_code = account.with_company(
                        company,
                    )._search_new_account_code(
                        start_code,
                        cache[company.id],
                    )
                    vals["code_mapping_ids"].append(
                        Command.create(
                            {
                                "company_id": company.id,
                                "code": new_code,
                            }
                        ),
                    )
                    cache[company.id].add(new_code)

            if "name" not in default:
                vals["name"] = self.env._(
                    "%s (copy)",
                    account.name or "",
                )

        return vals_list

    def copy_translations(self, new, excluded=()):
        super().copy_translations(new, excluded=(*excluded, "name"))
        self._copy_translations_of_renamed_field(
            new,
            "name",
            lambda record, term: record.env._("%s (copy)", term or ""),
        )

    @_debug.perf.timed
    def write(self, vals):
        _debug.lifecycle("write", records=self, fields=sorted(vals))
        _debug.logic(
            "write_guards",
            accounts=self,
            reconcile=vals.get("reconcile"),
            reconcile_toggled="reconcile" in vals,
            currency_check=bool(vals.get("currency_id")),
            deprecate_check=vals.get("active") is False,
        )
        if "reconcile" in vals:
            if vals["reconcile"]:
                self.filtered(
                    lambda r: not r.reconcile,
                )._toggle_reconcile_to_true()
            else:
                self.filtered(
                    lambda r: r.reconcile,
                )._toggle_reconcile_to_false()

        if vals.get("currency_id") and self.env["account.move.line"].search_count(
            [
                ("account_id", "in", self.ids),
                ("currency_id", "not in", (False, vals["currency_id"])),
            ],
            limit=1,
        ):
            raise UserError(
                self.env._(
                    "You cannot set a currency on this account as it "
                    "already has some journal entries having a different "
                    "foreign currency.",
                )
            )

        if vals.get("active") is False and self.env[
            "account.tax.repartition.line"
        ].search_count(
            [("account_id", "in", self.ids)],
            limit=1,
        ):
            raise UserError(
                self.env._(
                    "You cannot deprecate an account that is used in a "
                    "tax distribution.",
                )
            )

        res = super(
            AccountAccount,
            self.with_context(
                defer_account_code_checks=True,
                prefetch_fields=not any(
                    field in vals for field in ["code", "account_type"]
                ),
            ),
        ).write(vals)

        if (
            not self.env.context.get("defer_account_code_checks")
            and {"company_ids", "code", "code_mapping_ids"} & vals.keys()
        ):
            if "company_ids" in vals:
                self.invalidate_recordset(fnames=["company_ids"])
            self._check_code_is_unique()

        return res

    @api.constrains("reconcile", "account_type", "tax_ids")
    def _constrains_reconcile(self):
        for record in self:
            if record.account_type == "off_balance":
                if record.reconcile:
                    raise UserError(
                        self.env._("An Off-Balance account can not be reconcilable"),
                    )
                if record.tax_ids:
                    raise UserError(
                        self.env._("An Off-Balance account can not have taxes"),
                    )

    @api.constrains("currency_id")
    @_debug.perf.timed
    def _check_journal_consistency(self):
        if not self:
            return

        journals = (
            self.env["account.journal"]
            .sudo()
            .search(
                [("currency_id", "!=", False), ("default_account_id", "in", self.ids)]
            )
        )
        mismatched = [
            (journal.default_account_id, journal)
            for journal in journals
            if journal.currency_id != journal.company_id.currency_id
            # an account without a currency matched nothing in SQL: NULL != x is no row
            and journal.default_account_id.currency_id
            and journal.default_account_id.currency_id != journal.currency_id
        ]
        if not mismatched:
            channels = (
                self.env["account.payment.channel"]
                .sudo()
                .search(
                    [
                        ("payment_account_id", "in", self.ids),
                        ("journal_id.currency_id", "!=", False),
                        (
                            "payment_method_id.payment_type",
                            "in",
                            ("inbound", "outbound"),
                        ),
                    ]
                )
            )
            mismatched = [
                (channel.payment_account_id, channel.journal_id)
                for channel in channels
                if channel.journal_id.currency_id
                != channel.journal_id.company_id.currency_id
                and channel.payment_account_id.currency_id
                and channel.payment_account_id.currency_id
                != channel.journal_id.currency_id
            ]
        _debug.logic(
            "journal_currency_checked",
            accounts=self,
            mismatch=bool(mismatched),
        )
        if mismatched:
            account, journal = mismatched[0]
            raise ValidationError(
                self.env._(
                    "The foreign currency set on the journal '%(journal)s' and "
                    "the account '%(account)s' must be the same.",
                    journal=journal.display_name,
                    account=account.display_name,
                )
            )

    @api.constrains("company_ids")
    @_debug.perf.timed
    def _check_company_move_line_consistency(self):
        self.invalidate_recordset(fnames=["company_ids"])
        companies_by_account = defaultdict(set)
        for account, company in (
            self.env["account.move.line"]
            .sudo()
            ._read_group([("account_id", "in", self.ids)], ["account_id", "company_id"])
        ):
            companies_by_account[account.id].add(company)
        for companies, accounts in self.grouped(
            lambda a: a.company_ids,
        ).items():
            if any(
                not (companies & company.parent_ids)
                for account in accounts
                for company in companies_by_account[account.id]
            ):
                raise UserError(
                    self.env._(
                        "You can't unlink this company from this account since "
                        "there are some journal items linked to it.",
                    )
                )

    @api.constrains("account_type")
    @_debug.perf.timed
    def _check_account_type_sales_purchase_journal(self):
        if not self:
            return

        used = (
            self.env["account.journal"]
            .sudo()
            .search_count(
                [
                    ("type", "in", ("sale", "purchase")),
                    ("default_account_id", "in", self.ids),
                    (
                        "default_account_id.account_type",
                        "in",
                        ("asset_receivable", "liability_payable"),
                    ),
                ],
                limit=1,
            )
        )
        if used:
            _debug.logic(
                "account_type_rejected", accounts=self, reason="sale_purchase_journal"
            )
            raise ValidationError(
                self.env._(
                    "The account is already in use in a 'sale' or 'purchase' "
                    "journal. This means that the account's type couldn't be "
                    "'receivable' or 'payable'.",
                )
            )

    @api.constrains("account_type")
    @_debug.perf.timed
    def _check_account_is_bank_journal_bank_account(self):
        used = (
            self.env["account.journal"]
            .sudo()
            .search_count(
                [
                    ("default_account_id", "in", self.ids),
                    (
                        "default_account_id.account_type",
                        "in",
                        ("asset_receivable", "liability_payable"),
                    ),
                ],
                limit=1,
            )
        )
        if used:
            _debug.logic(
                "account_type_rejected", accounts=self, reason="bank_journal_account"
            )
            raise ValidationError(
                self.env._(
                    "You cannot change the type of an account set as Bank "
                    "Account on a journal to Receivable or Payable.",
                )
            )

    @api.model
    @api.readonly
    @_debug.perf.timed
    def name_search(self, name="", domain=None, operator="ilike", limit=100):
        move_type = self.env.context.get("move_type")
        if _debug.logic.enabled and not move_type:
            _debug.logic("name_search_fallback", reason="no_move_type")
        if not move_type:
            return super().name_search(name, domain, operator, limit)

        domain = domain or []
        partner = self.env.context.get("partner_id")
        suggested_accounts = (
            self._get_most_frequent_accounts_for_partner(
                self.env.company.id,
                partner,
                move_type,
            )
            if partner
            else []
        )
        _debug.logic(
            "suggested_accounts_resolved",
            partner=partner,
            move_type=move_type,
            suggested=len(suggested_accounts),
            shortcut=not name and bool(suggested_accounts),
        )

        if not name and suggested_accounts:
            display_by_id = {
                record.id: record.display_name
                for record in self.search_fetch(
                    Domain.AND([[("id", "in", suggested_accounts)], domain]),
                    ["display_name"],
                )
            }
            return [
                (account_id, display_by_id[account_id])
                for account_id in suggested_accounts
                if account_id in display_by_id
            ][:limit]

        digit_in_search_term = any(c.isdigit() for c in name)
        search_domain = Domain("display_name", "ilike", name) if name else []

        if digit_in_search_term:
            domain = Domain.AND([search_domain, domain])
        else:
            allowed_account_types = self._get_name_search_account_types(move_type)
            type_domain = (
                [("account_type", "in", allowed_account_types)]
                if allowed_account_types
                else []
            )
            domain = Domain.AND([search_domain, type_domain, domain])

        _debug.logic(
            "name_search_domain_chosen",
            move_type=move_type,
            by_digits=digit_in_search_term,
            limit=limit,
        )
        records = self.with_context(
            preferred_account_ids=suggested_accounts,
        ).search_fetch(domain, ["display_name"], limit=limit)
        return [(record.id, record.display_name) for record in records]

    @api.ondelete(at_uninstall=False)
    @_debug.perf.timed
    def _unlink_except_contains_journal_items(self):
        _debug.lifecycle("_unlink_except_contains_journal_items", records=self)
        if (
            self.env["account.move.line"]
            .sudo()
            .search_count(
                [("account_id", "in", self.ids)],
                limit=1,
            )
        ):
            raise UserError(
                self.env._(
                    "You cannot perform this action on an account that "
                    "contains journal items.",
                )
            )

    @api.ondelete(at_uninstall=False)
    @_debug.perf.timed
    def _unlink_except_linked_to_fiscal_position(self):
        _debug.lifecycle("_unlink_except_linked_to_fiscal_position", records=self)
        if self.env["account.fiscal.position.account"].search_count(
            [
                "|",
                ("account_src_id", "in", self.ids),
                ("account_dest_id", "in", self.ids),
            ],
            limit=1,
        ):
            raise UserError(
                self.env._(
                    'You cannot remove/deactivate the accounts "%s" which '
                    "are set on the account mapping of a fiscal position.",
                    ", ".join(f"{a.code} - {a.name}" for a in self),
                )
            )

    @api.ondelete(at_uninstall=False)
    @_debug.perf.timed
    def _unlink_except_linked_to_tax_repartition_line(self):
        _debug.lifecycle("_unlink_except_linked_to_tax_repartition_line", records=self)
        if self.env["account.tax.repartition.line"].search_count(
            [("account_id", "in", self.ids)],
            limit=1,
        ):
            raise UserError(
                self.env._(
                    'You cannot remove/deactivate the accounts "%s" which '
                    "are set on a tax repartition line.",
                    ", ".join(f"{a.code} - {a.name}" for a in self),
                )
            )

    @api.depends_context("company")
    def _compute_company_fiscal_country_code(self):
        self.company_fiscal_country_code = (
            self.env.company.tax_config_id.account_fiscal_country_id.code
        )

    @api.depends_context("company")
    @api.depends("code")
    @_debug.perf.timed
    def _compute_group_id(self):
        accounts_with_code = self.filtered(lambda a: a.code)
        _debug.pipeline(
            "group_codes_scope",
            accounts=self,
            with_code=accounts_with_code,
        )

        (self - accounts_with_code).group_id = False

        if not accounts_with_code:
            return

        codes = accounts_with_code.mapped("code")
        account_code_values = SQL(
            ",".join(["(%s)"] * len(codes)),
            *codes,
        )
        results = self.env.execute_query(
            SQL(
                """
                 SELECT DISTINCT ON (account_code.code)
                        account_code.code,
                        agroup.id AS group_id
                   FROM (VALUES %(account_code_values)s)
                        AS account_code (code)
              LEFT JOIN account_group agroup
                     ON agroup.code_prefix_start
                        <= LEFT(account_code.code,
                                char_length(agroup.code_prefix_start))
                        AND agroup.code_prefix_end
                        >= LEFT(account_code.code,
                                char_length(agroup.code_prefix_end))
                        AND agroup.company_id = %(root_company_id)s
               ORDER BY account_code.code,
                    char_length(agroup.code_prefix_start) DESC, agroup.id
            """,
                account_code_values=account_code_values,
                root_company_id=self.env.company.root_id.id,
            )
        )
        group_by_code = dict(results)
        if _debug.pipeline.enabled:
            _debug.pipeline(
                "groups_resolved",
                codes=len(codes),
                grouped=sum(1 for group_id in group_by_code.values() if group_id),
                root_company=self.env.company.root_id,
            )

        for account in accounts_with_code:
            account.group_id = group_by_code[account.code]

    def _compute_used(self):
        used = set(self._get_used_account_ids(self.ids))
        for record in self:
            record.used = record.id in used

    @api.depends_context("company")
    def _compute_current_balance(self):
        balances = {
            account.id: balance
            for account, balance in self.env["account.move.line"]._read_group(
                domain=[
                    ("account_id", "in", self.ids),
                    ("parent_state", "=", "posted"),
                    ("company_id", "child_of", self.env.company.id),
                ],
                groupby=["account_id"],
                aggregates=["balance:sum"],
            )
        }
        for record in self:
            record.current_balance = balances.get(record.id, 0)

    @api.depends_context("company")
    def _compute_related_taxes_amount(self):
        counts = dict(
            self.env["account.tax.repartition.line"]._read_group(
                domain=[
                    ("account_id", "in", self.ids),
                    *self.env["account.tax"]._check_company_domain(
                        self.env.company,
                    ),
                ],
                groupby=["account_id"],
                aggregates=["tax_id:count_distinct"],
            )
        )
        for record in self:
            record.related_taxes_amount = counts.get(record, 0)

    @api.depends_context("company")
    @_debug.perf.timed
    def _compute_opening_debit_credit(self):
        self.opening_debit = 0
        self.opening_credit = 0
        self.opening_balance = 0
        opening_move = self.env.company.account_config_id.account_opening_move_id
        _debug.logic(
            "opening_move_source",
            accounts=self,
            move=opening_move,
            skipped=not self.ids or not opening_move,
        )
        if not self.ids or not opening_move:
            return
        self.env.cr.execute(
            SQL(
                """
            SELECT line.account_id,
                   SUM(line.balance) AS balance,
                   SUM(line.debit) AS debit,
                   SUM(line.credit) AS credit
              FROM account_move_line line
             WHERE line.move_id = %(opening_move_id)s
               AND line.account_id IN %(account_ids)s
             GROUP BY line.account_id
            """,
                account_ids=tuple(self.ids),
                opening_move_id=opening_move.id,
            )
        )
        result = {r["account_id"]: r for r in self.env.cr.dictfetchall()}
        _debug.perf.count("opening_balance_rows", rows=len(result))
        for record in self:
            res = result.get(record.id) or {
                "debit": 0,
                "credit": 0,
                "balance": 0,
            }
            record.opening_debit = res["debit"]
            record.opening_credit = res["credit"]
            record.opening_balance = res["balance"]

    @api.depends_context(
        "company",
        "formatted_display_name",
        "uid",
        "move_type",
        "partner_id",
        "preferred_account_ids",
    )
    @api.depends("code")
    @_debug.perf.timed
    def _compute_display_name(self):
        formatted_display_name = self.env.context.get(
            "formatted_display_name",
        )
        new_line = "\n"
        preferred_account_ids = self.env.context.get(
            "preferred_account_ids",
            [],
        )
        _debug.logic(
            "display_name_mode",
            accounts=self,
            formatted=bool(formatted_display_name),
            preferred_in_context=bool(preferred_account_ids),
        )
        if (
            formatted_display_name
            and (move_type := self.env.context.get("move_type"))
            and (partner := self.env.context.get("partner_id"))
            and not preferred_account_ids
        ):
            preferred_account_ids = self._get_most_frequent_accounts_for_partner(
                self.env.company.id,
                partner,
                move_type,
            )
        _debug.logic(
            "display_name_preferred",
            preferred=len(preferred_account_ids or ()),
        )
        for account in self:
            if formatted_display_name and account.code:
                suggested = (
                    f" `{self.env._('Suggested')}`"
                    if account.id in preferred_account_ids
                    else ""
                )
                desc = (
                    f"{new_line}--{account.description}--"
                    if account.description
                    else ""
                )
                code_part = (
                    account.code
                    if self.env.user.has_group("account.group_account_readonly")
                    else ""
                )
                account.display_name = f"{code_part} {account.name}{suggested}{desc}"
            else:
                account.display_name = (
                    f"{account.code} {account.name}"
                    if account.code
                    and self.env.user.has_group(
                        "account.group_account_readonly",
                    )
                    else account.name
                )

    @_debug.perf.timed
    def _search_used(self, operator, value):
        if operator not in ("in", "not in"):
            return NotImplemented
        return [("id", operator, self._get_used_account_ids())]

    def _inverse_opening_debit(self):
        for record in self:
            record._set_opening_debit_credit(record.opening_debit, "debit")

    def _inverse_opening_credit(self):
        for record in self:
            record._set_opening_debit_credit(record.opening_credit, "credit")

    def _inverse_opening_balance(self):
        for account in self:
            balance = account.opening_balance
            account._set_opening_debit_credit(
                abs(balance) if balance > 0.0 else 0.0,
                "debit",
            )
            account._set_opening_debit_credit(
                abs(balance) if balance < 0.0 else 0.0,
                "credit",
            )

    def _set_opening_debit_credit(self, amount, field):
        self.check_singleton()
        if "import_account_opening_balance" not in self.env.cr.precommit.data:
            data = self.env.cr.precommit.data["import_account_opening_balance"] = {}
            self.env.cr.precommit.add(
                self._load_precommit_update_opening_move,
            )
        else:
            data = self.env.cr.precommit.data["import_account_opening_balance"]
        data.setdefault(self.env.company.id, {}).setdefault(
            self.id,
            [None, None],
        )
        index = 0 if field == "debit" else 1
        data[self.env.company.id][self.id][index] = amount

    @api.onchange("account_type")
    def _onchange_account_type(self):
        if self.account_type == "off_balance":
            self.tax_ids = False

    @api.model
    @_debug.perf.timed
    def _load_precommit_update_opening_move(self):
        data = self.env.cr.precommit.data.pop(
            "import_account_opening_balance",
            {},
        )

        for company_id, account_values in data.items():
            self.env["res.company"].browse(company_id)._update_opening_move(
                {
                    self.env["account.account"].browse(account_id): values
                    for account_id, values in account_values.items()
                }
            )

        self.env.flush_all()

    def _toggle_reconcile_to_true(self):
        if not self.ids:
            return
        self.env["account.move.line"].invalidate_model(
            [
                "amount_residual",
                "amount_residual_currency",
                "reconciled",
            ]
        )
        query = """
            UPDATE account_move_line SET
                reconciled = CASE WHEN debit = 0 AND credit = 0
                    AND amount_currency = 0
                    THEN true ELSE false END,
                amount_residual = (debit-credit),
                amount_residual_currency = amount_currency
            WHERE full_reconcile_id IS NULL and account_id = ANY(%s)
        """
        self.env.cr.execute(query, [list(self.ids)])
        _debug.lifecycle(
            "reconcile_true_reset", account=self, rowcount=self.env.cr.rowcount
        )

    @_debug.perf.timed
    def _toggle_reconcile_to_false(self):
        if not self.ids:
            return
        partial_lines_count = self.env["account.move.line"].search_count(
            [
                ("account_id", "in", self.ids),
                ("full_reconcile_id", "=", False),
                ("|"),
                ("matched_debit_ids", "!=", False),
                ("matched_credit_ids", "!=", False),
            ],
            limit=1,
        )
        _debug.logic(
            "partial_reconciles_pending",
            accounts=self,
            pending=partial_lines_count,
        )
        if partial_lines_count > 0:
            raise UserError(
                self.env._(
                    "You cannot switch an account to prevent the reconciliation "
                    "if some partial reconciliations are still pending.",
                )
            )

        self.env["account.move.line"].invalidate_model(
            [
                "amount_residual",
                "amount_residual_currency",
            ]
        )
        query = """
            UPDATE account_move_line
                SET amount_residual = 0, amount_residual_currency = 0
            WHERE full_reconcile_id IS NULL AND account_id = ANY(%s)
        """
        self.env.cr.execute(query, [list(self.ids)])
        _debug.lifecycle(
            "reconcile_false_zeroed", account=self, rowcount=self.env.cr.rowcount
        )

    def _get_used_account_ids(self, account_ids=None):
        rows = self.env.execute_query(
            SQL(
                """
                SELECT account.id
                  FROM account_account account
                 WHERE EXISTS (
                           SELECT 1 FROM account_move_line aml
                            WHERE aml.account_id = account.id
                       )
                       %s
                """,
                SQL("AND account.id = ANY(%s)", list(account_ids))
                if account_ids is not None
                else SQL(),
            )
        )
        _debug.perf.count("used_accounts_fetched", rows=len(rows))
        return [r[0] for r in rows]

    @api.model
    @_debug.perf.timed
    def _get_most_frequent_accounts_for_partner(
        self,
        company_id,
        partner_id,
        move_type,
        limit=None,
    ):
        domain = [
            *self.env["account.move.line"]._check_company_domain(company_id),
            ("partner_id", "=", partner_id),
            ("account_id.active", "=", True),
            (
                "date",
                ">=",
                fields.Date.add(
                    fields.Date.today(),
                    days=-365 * 2,
                ),
            ),
        ]
        suggestion_domain = self._get_suggestion_account_domain(move_type)
        if not suggestion_domain.is_true():
            domain.append(("account_id", "any", suggestion_domain))
        if document_types := self._get_suggestion_move_types(move_type):
            domain.append(("move_id.move_type", "in", document_types))

        query = self.env["account.move.line"]._search(
            domain,
            bypass_access=True,
        )
        if _debug.logic.enabled:
            _debug.logic(
                "frequency_query_shaped",
                company=company_id,
                partner=partner_id,
                move_type=move_type,
                suggestion_domain=str(suggestion_domain),
                limit=limit,
            )

        company = self.env["res.company"].browse(company_id)
        code_sql = self.with_company(company)._field_to_sql(
            "account_move_line__account_id",
            "code",
            query,
        )

        return [
            r[0]
            for r in self.env.execute_query(
                SQL(
                    """
                SELECT account_move_line__account_id.id
                  FROM %(from_clause)s
                 WHERE %(where_clause)s
              GROUP BY account_move_line__account_id.id
              ORDER BY COUNT(account_move_line.id) DESC,
                       MAX(%(code_sql)s)
                %(limit_clause)s
            """,
                    from_clause=query.from_clause,
                    where_clause=query.where_clause or SQL("TRUE"),
                    code_sql=code_sql,
                    limit_clause=SQL("LIMIT %s", limit) if limit else SQL(),
                )
            )
        ]

    @api.model
    def _get_most_frequent_account_for_partner(
        self,
        company_id,
        partner_id,
        move_type=None,
    ):
        cache = self.env.cr.cache.setdefault("most_frequent_accounts_for_partner", {})
        key = (company_id, partner_id, move_type)

        if key not in cache:
            most_frequent_account = self._get_most_frequent_accounts_for_partner(
                company_id,
                partner_id,
                move_type,
                limit=1,
            )
            cache[key] = most_frequent_account[0] if most_frequent_account else False

        return cache[key]

    @_debug.perf.timed
    def _order_to_sql(
        self,
        order: str,
        query: Query,
        alias: (str | None) = None,
        reverse: bool = False,
    ) -> SQL:
        sql_order = super()._order_to_sql(order, query, alias, reverse)

        if order == self._order and (
            preferred_account_type := self.env.context.get(
                "preferred_account_type",
            )
        ):
            sql_order = SQL(
                "%(field_sql)s = %(preferred_account_type)s "
                "%(direction)s, %(base_order)s",
                field_sql=self._field_to_sql(
                    alias or self._table,
                    "account_type",
                ),
                preferred_account_type=preferred_account_type,
                direction=SQL("ASC") if reverse else SQL("DESC"),
                base_order=sql_order,
            )
        if order == self._order and (
            preferred_account_ids := self.env.context.get(
                "preferred_account_ids",
            )
        ):
            sql_order = SQL(
                "%(alias)s.id in %(preferred_account_ids)s "
                "%(direction)s, %(base_order)s",
                alias=SQL.identifier(alias or self._table),
                preferred_account_ids=tuple(
                    map(int, preferred_account_ids),
                ),
                direction=SQL("ASC") if reverse else SQL("DESC"),
                base_order=sql_order,
            )
        if _debug.logic.enabled and order == self._order:
            _debug.logic(
                "account_order_preferred",
                preferred_type=self.env.context.get("preferred_account_type"),
                preferred_ids=bool(self.env.context.get("preferred_account_ids")),
                reverse=reverse,
            )
        return sql_order

    def _get_suggestion_account_domain(self, move_type):
        side = (move_type or "").split("_")[0]
        if side == "out":
            return Domain("internal_group", "=", "income")
        if side == "in":
            return Domain("internal_group", "=", "expense") | Domain(
                "account_type", "=", "asset_fixed"
            )
        return Domain.TRUE

    def _get_suggestion_move_types(self, move_type):
        AccountMove = self.env["account.move"]
        return {
            "out": AccountMove.get_sale_types(include_receipts=True),
            "in": AccountMove.get_purchase_types(include_receipts=True),
        }.get((move_type or "").split("_")[0], [])

    def _get_name_search_account_types(self, move_type):
        move_type_accounts = {
            "out": ["income"],
            "in": ["expense", "asset_fixed", "expense_direct_cost"],
        }
        return move_type_accounts.get((move_type or "").split("_")[0])

    @_debug.perf.timed
    def action_view_related_taxes(self):
        _debug.lifecycle("action_view_related_taxes", records=self)
        related_taxes_ids = (
            self.env["account.tax"]
            .search(
                [
                    ("repartition_line_ids.account_id", "=", self.id),
                ]
            )
            .ids
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Taxes"),
            "res_model": "account.tax",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("id", "in", related_taxes_ids)],
        }

    @_debug.perf.timed
    def action_view_reconcile(self):
        _debug.lifecycle("action_view_reconcile", records=self)
        self.check_singleton()
        return self.env["account.move.line"]._action_view_unreconciled(
            extra_domain=[("account_id", "=", self.id)],
        )

    @api.model
    def get_import_templates(self):
        return [
            {
                "label": self.env._("Import Template for Chart of Accounts"),
                "template": "/account/static/xls/coa_import_template.xlsx",
            }
        ]

    def _merge_method(self, destination, source):
        raise UserError(self.env._("You cannot merge accounts."))

    def _unmerge_action_xmlid(self):
        return "account.action_unmerge_accounts"

    def _unmerge_copy_defaults(self):
        return {"name": self.name}
