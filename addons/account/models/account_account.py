import contextlib
import json

from odoo import Command, _, api, fields, models
from odoo.exceptions import RedirectWarning, UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import SQL, Query


class AccountAccount(models.Model):
    """Accounting extensions to the base chart of accounts."""

    _name = "account.account"
    _inherit = ["account.account", "mail.thread", "mail.activity.mixin"]

    # ------------------------------------------------------------------
    # Additional fields (accounting-specific)
    # ------------------------------------------------------------------

    # Re-declare with tracking (base_account defines without tracking)
    name = fields.Char(tracking=True)
    currency_id = fields.Many2one(tracking=True)
    active = fields.Boolean(tracking=True)
    account_type = fields.Selection(tracking=True)
    reconcile = fields.Boolean(tracking=True)
    note = fields.Text(tracking=True)
    tag_ids = fields.Many2many(tracking=True)

    company_fiscal_country_code = fields.Char(
        compute="_compute_company_fiscal_country_code",
    )
    tax_ids = fields.Many2many(
        "account.tax",
        "account_account_tax_default_rel",
        "account_id",
        "tax_id",
        string="Default Taxes",
        check_company=True,
        context={"append_fields": ["type_tax_use", "company_id"]},
    )
    group_id = fields.Many2one(
        "account.group",
        compute="_compute_account_group",
        help="Account prefixes can determine account groups.",
    )
    used = fields.Boolean(compute="_compute_used", search="_search_used")
    opening_debit = fields.Monetary(
        string="Opening Debit",
        compute="_compute_opening_debit_credit",
        inverse="_set_opening_debit",
        currency_field="company_currency_id",
    )
    opening_credit = fields.Monetary(
        string="Opening Credit",
        compute="_compute_opening_debit_credit",
        inverse="_set_opening_credit",
        currency_field="company_currency_id",
    )
    opening_balance = fields.Monetary(
        string="Opening Balance",
        compute="_compute_opening_debit_credit",
        inverse="_set_opening_balance",
        currency_field="company_currency_id",
    )
    current_balance = fields.Float(compute="_compute_current_balance")
    related_taxes_amount = fields.Integer(
        compute="_compute_related_taxes_amount",
    )

    # ------------------------------------------------------------------
    # Constraints (accounting-specific)
    # ------------------------------------------------------------------

    @api.constrains("reconcile", "account_type", "tax_ids")
    def _constrains_reconcile(self):
        for record in self:
            if record.account_type == "off_balance":
                if record.reconcile:
                    raise UserError(
                        _("An Off-Balance account can not be reconcilable"),
                    )
                if record.tax_ids:
                    raise UserError(
                        _("An Off-Balance account can not have taxes"),
                    )

    @api.constrains("currency_id")
    def _check_journal_consistency(self):
        """Ensure the currency on the journal matches the account currency."""
        if not self:
            return

        self.env["account.account"].flush_model(["currency_id"])
        self.env["account.journal"].flush_model(
            [
                "currency_id",
                "default_account_id",
                "suspense_account_id",
            ]
        )
        self.env["account.payment.method"].flush_model(["payment_type"])
        self.env["account.payment.method.line"].flush_model(
            [
                "payment_method_id",
                "payment_account_id",
            ]
        )

        self.env.cr.execute(
            """
            SELECT
                account.id,
                journal.id
            FROM account_journal journal
            JOIN res_company company ON company.id = journal.company_id
            JOIN account_account account ON account.id = journal.default_account_id
            WHERE journal.currency_id IS NOT NULL
            AND journal.currency_id != company.currency_id
            AND account.currency_id != journal.currency_id
            AND account.id = ANY(%(accounts)s)

            UNION ALL

            SELECT
                account.id,
                journal.id
            FROM account_journal journal
            JOIN res_company company ON company.id = journal.company_id
            JOIN account_payment_method_line apml ON apml.journal_id = journal.id
            JOIN account_payment_method apm on apm.id = apml.payment_method_id
            JOIN account_account account ON account.id = apml.payment_account_id
            WHERE journal.currency_id IS NOT NULL
            AND journal.currency_id != company.currency_id
            AND account.currency_id != journal.currency_id
            AND apm.payment_type IN ('inbound', 'outbound')
            AND account.id = ANY(%(accounts)s)
        """,
            {"accounts": list(self.ids)},
        )
        res = self.env.cr.fetchone()
        if res:
            account = self.env["account.account"].browse(res[0])
            journal = self.env["account.journal"].browse(res[1])
            raise ValidationError(
                _(
                    "The foreign currency set on the journal '%(journal)s' and "
                    "the account '%(account)s' must be the same.",
                    journal=journal.display_name,
                    account=account.display_name,
                )
            )

    @api.constrains("company_ids")
    def _check_company_move_line_consistency(self):
        """Prevent removing a company that has journal items."""
        self.invalidate_recordset(fnames=["company_ids"])
        for companies, accounts in self.grouped(
            lambda a: a.company_ids,
        ).items():
            if (
                self.env["account.move.line"]
                .sudo()
                .search_count(
                    [
                        ("account_id", "in", accounts.ids),
                        "!",
                        ("company_id", "child_of", companies.ids),
                    ],
                    limit=1,
                )
            ):
                raise UserError(
                    _(
                        "You can't unlink this company from this account since "
                        "there are some journal items linked to it.",
                    )
                )

    @api.constrains("account_type")
    def _check_account_type_sales_purchase_journal(self):
        if not self:
            return

        self.env["account.account"].flush_model(["account_type"])
        self.env["account.journal"].flush_model(
            [
                "type",
                "default_account_id",
            ]
        )
        self.env.cr.execute(
            """
            SELECT account.id
            FROM account_account account
            JOIN account_journal journal
                ON journal.default_account_id = account.id
            WHERE account.id = ANY(%s)
            AND account.account_type
                IN ('asset_receivable', 'liability_payable')
            AND journal.type IN ('sale', 'purchase')
            LIMIT 1;
        """,
            [list(self.ids)],
        )

        if self.env.cr.fetchone():
            raise ValidationError(
                _(
                    "The account is already in use in a 'sale' or 'purchase' "
                    "journal. This means that the account's type couldn't be "
                    "'receivable' or 'payable'.",
                )
            )

    @api.constrains("account_type")
    def _check_account_is_bank_journal_bank_account(self):
        self.env["account.account"].flush_model(["account_type"])
        self.env["account.journal"].flush_model(
            [
                "type",
                "default_account_id",
            ]
        )
        self.env.cr.execute(
            """
            SELECT journal.id
              FROM account_journal journal
              JOIN account_account account
                ON journal.default_account_id = account.id
             WHERE account.account_type
                IN ('asset_receivable', 'liability_payable')
               AND account.id = ANY(%s)
             LIMIT 1;
        """,
            [list(self.ids)],
        )

        if self.env.cr.fetchone():
            raise ValidationError(
                _(
                    "You cannot change the type of an account set as Bank "
                    "Account on a journal to Receivable or Payable.",
                )
            )

    # ------------------------------------------------------------------
    # Computed fields (accounting-specific)
    # ------------------------------------------------------------------

    @api.depends_context("company")
    def _compute_company_fiscal_country_code(self):
        self.company_fiscal_country_code = (
            self.env.company.account_fiscal_country_id.code
        )

    @api.depends_context("company")
    @api.depends("code")
    def _compute_account_group(self):
        accounts_with_code = self.filtered(lambda a: a.code)

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

        for account in accounts_with_code:
            account.group_id = group_by_code[account.code]

    def _get_used_account_ids(self, account_ids=None):
        """Return ids of accounts that carry at least one journal item.

        :param account_ids: restrict the scan to these accounts (the compute
            path); when omitted, every account is considered (the search path,
            which is global by nature).
        """
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
        return [r[0] for r in rows]

    def _search_used(self, operator, value):
        # ``used`` is a boolean; the ORM normalises every realistic domain to
        # ``in [True]`` / ``not in [True]``, so the operator alone carries the
        # meaning and ``value`` needs no further inspection.
        if operator not in ("in", "not in"):
            return NotImplemented
        return [("id", operator, self._get_used_account_ids())]

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
        # One grouped query for the whole recordset instead of a search_count
        # per record. A tax is counted once even if several of its repartition
        # lines target the same account.
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
    def _compute_opening_debit_credit(self):
        self.opening_debit = 0
        self.opening_credit = 0
        self.opening_balance = 0
        opening_move = self.env.company.account_opening_move_id
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
        for record in self:
            res = result.get(record.id) or {
                "debit": 0,
                "credit": 0,
                "balance": 0,
            }
            record.opening_debit = res["debit"]
            record.opening_credit = res["credit"]
            record.opening_balance = res["balance"]

    @api.depends_context("company", "formatted_display_name")
    @api.depends("code")
    def _compute_display_name(self):
        """Override base_account's display_name to add accounting features."""
        formatted_display_name = self.env.context.get(
            "formatted_display_name",
        )
        new_line = "\n"
        preferred_account_ids = self.env.context.get(
            "preferred_account_ids",
            [],
        )
        if (
            (move_type := self.env.context.get("move_type"))
            and (partner := self.env.context.get("partner_id"))
            and not preferred_account_ids
        ):
            preferred_account_ids = self._order_accounts_by_frequency_for_partner(
                self.env.company.id,
                partner,
                move_type,
            )
        for account in self:
            if formatted_display_name and account.code:
                suggested = (
                    f" `{_('Suggested')}`"
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

    # ------------------------------------------------------------------
    # Onchange (accounting-specific)
    # ------------------------------------------------------------------

    @api.onchange("account_type")
    def _onchange_account_type(self):
        if self.account_type == "off_balance":
            self.tax_ids = False

    # ------------------------------------------------------------------
    # Opening balance helpers
    # ------------------------------------------------------------------

    def _set_opening_debit(self):
        for record in self:
            record._set_opening_debit_credit(record.opening_debit, "debit")

    def _set_opening_credit(self):
        for record in self:
            record._set_opening_debit_credit(record.opening_credit, "credit")

    def _set_opening_balance(self):
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
        """Set opening debit/credit, batched via precommit callback."""
        self.ensure_one()
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

    @api.model
    def _load_precommit_update_opening_move(self):
        """Precommit callback to batch-update opening move balances."""
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

    # ------------------------------------------------------------------
    # Reconcile toggle
    # ------------------------------------------------------------------

    def _toggle_reconcile_to_true(self):
        """Toggle reconcile from False to True."""
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

    def _toggle_reconcile_to_false(self):
        """Toggle reconcile from True to False."""
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
        if partial_lines_count > 0:
            raise UserError(
                _(
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

    # ------------------------------------------------------------------
    # Name search / ordering (accounting-specific)
    # ------------------------------------------------------------------

    @api.model
    def _get_most_frequent_accounts_for_partner(
        self,
        company_id,
        partner_id,
        move_type,
        filter_never_used_accounts=False,
        limit=None,
    ):
        """Return account IDs ordered by usage frequency for a partner."""
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
        if move_type in self.env["account.move"].get_inbound_types(
            include_receipts=True,
        ):
            domain.append(("account_id.internal_group", "=", "income"))
        elif move_type in self.env["account.move"].get_outbound_types(
            include_receipts=True,
        ):
            domain.append(("account_id.internal_group", "=", "expense"))

        query = self.env["account.move.line"]._search(
            domain,
            bypass_access=True,
        )
        if not filter_never_used_accounts:
            # Promote the account join to a RIGHT JOIN so accounts that were
            # never used still show up (with a zero count). This reaches into
            # the Query's private join map; keep in sync with the ORM's join
            # key format ("<table>__<field>").
            _kind, rhs_table, condition = query._joins["account_move_line__account_id"]
            query._joins["account_move_line__account_id"] = (
                SQL("RIGHT JOIN"),
                rhs_table,
                condition,
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
                filter_never_used_accounts=True,
                limit=1,
            )
            cache[key] = most_frequent_account[0] if most_frequent_account else False

        return cache[key]

    @api.model
    def _order_accounts_by_frequency_for_partner(
        self,
        company_id,
        partner_id,
        move_type=None,
    ):
        return self._get_most_frequent_accounts_for_partner(
            company_id,
            partner_id,
            move_type,
        )

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
        return sql_order

    def _get_name_search_account_types(self, move_type):
        move_type_accounts = {
            "out": ["income"],
            "in": ["expense", "asset_fixed", "expense_direct_cost"],
        }
        return move_type_accounts.get(move_type.split("_")[0])

    @api.model
    @api.readonly
    def name_search(self, name="", domain=None, operator="ilike", limit=100):
        move_type = self.env.context.get("move_type")
        if not move_type:
            return super().name_search(name, domain, operator, limit)

        partner = self.env.context.get("partner_id")
        suggested_accounts = (
            self._order_accounts_by_frequency_for_partner(
                self.env.company.id,
                partner,
                move_type,
            )
            if partner
            else []
        )

        if not name and suggested_accounts:
            # Honour the caller-supplied domain and access rules even without a
            # search term, while preserving the by-frequency ordering of the
            # survivors.
            display_by_id = {
                record.id: record.display_name
                for record in self.search_fetch(
                    Domain.AND([[("id", "in", suggested_accounts)], domain or []]),
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

        records = self.with_context(
            preferred_account_ids=suggested_accounts,
        ).search_fetch(domain, ["display_name"], limit=limit)
        return [(record.id, record.display_name) for record in records]

    # ------------------------------------------------------------------
    # CRUD overrides (accounting-specific)
    # ------------------------------------------------------------------

    def write(self, vals):
        if "reconcile" in vals:
            if vals["reconcile"]:
                self.filtered(
                    lambda r: not r.reconcile,
                )._toggle_reconcile_to_true()
            else:
                self.filtered(
                    lambda r: r.reconcile,
                )._toggle_reconcile_to_false()

        if vals.get("currency_id"):
            for account in self:
                if self.env["account.move.line"].search_count(
                    [
                        ("account_id", "=", account.id),
                        ("currency_id", "not in", (False, vals["currency_id"])),
                    ],
                    limit=1,
                ):
                    raise UserError(
                        _(
                            "You cannot set a currency on this account as it "
                            "already has some journal entries having a different "
                            "foreign currency.",
                        )
                    )

        if vals.get("deprecated") and self.env[
            "account.tax.repartition.line"
        ].search_count(
            [("account_id", "in", self.ids)],
            limit=1,
        ):
            raise UserError(
                _(
                    "You cannot deprecate an account that is used in a "
                    "tax distribution.",
                )
            )

        return super().write(vals)

    # ------------------------------------------------------------------
    # Delete guards (accounting-specific)
    # ------------------------------------------------------------------

    @api.ondelete(at_uninstall=False)
    def _unlink_except_contains_journal_items(self):
        if (
            self.env["account.move.line"]
            .sudo()
            .search_count(
                [("account_id", "in", self.ids)],
                limit=1,
            )
        ):
            raise UserError(
                _(
                    "You cannot perform this action on an account that "
                    "contains journal items.",
                )
            )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_linked_to_fiscal_position(self):
        if self.env["account.fiscal.position.account"].search_count(
            [
                "|",
                ("account_src_id", "in", self.ids),
                ("account_dest_id", "in", self.ids),
            ],
            limit=1,
        ):
            raise UserError(
                _(
                    'You cannot remove/deactivate the accounts "%s" which '
                    "are set on the account mapping of a fiscal position.",
                    ", ".join(f"{a.code} - {a.name}" for a in self),
                )
            )

    @api.ondelete(at_uninstall=False)
    def _unlink_except_linked_to_tax_repartition_line(self):
        if self.env["account.tax.repartition.line"].search_count(
            [("account_id", "in", self.ids)],
            limit=1,
        ):
            raise UserError(
                _(
                    'You cannot remove/deactivate the accounts "%s" which '
                    "are set on a tax repartition line.",
                    ", ".join(f"{a.code} - {a.name}" for a in self),
                )
            )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_open_related_taxes(self):
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
            "name": _("Taxes"),
            "res_model": "account.tax",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("id", "in", related_taxes_ids)],
        }

    @api.model
    def get_import_templates(self):
        return [
            {
                "label": _("Import Template for Chart of Accounts"),
                "template": "/account/static/xls/coa_import_template.xlsx",
            }
        ]

    def _merge_method(self, destination, source):
        raise UserError(_("You cannot merge accounts."))

    # ------------------------------------------------------------------
    # Unmerge
    # ------------------------------------------------------------------

    def action_unmerge(self):
        """Split the account into one per company."""
        self._check_action_unmerge_possible()
        self._action_unmerge_get_user_confirmation()

        for account in self.with_context(
            {
                "allowed_company_ids": (
                    self.env.company | self.env.user.company_ids
                ).ids,
            }
        ):
            account._action_unmerge()

        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def _check_action_unmerge_possible(self):
        """Raise an error if the recordset cannot be unmerged."""
        self.check_access("write")

        if forbidden_companies := (self.sudo().company_ids - self.env.user.company_ids):
            raise UserError(
                _(
                    "You do not have the right to perform this operation as "
                    "you do not have access to the following companies: %s.",
                    ", ".join(c.name for c in forbidden_companies),
                )
            )
        for account in self:
            if len(account.company_ids) == 1:
                raise UserError(
                    _(
                        "Account %s cannot be unmerged as it already belongs "
                        "to a single company. The unmerge operation only "
                        "splits an account based on its companies.",
                        account.display_name,
                    )
                )

    def _action_unmerge_get_user_confirmation(self):
        """Open a RedirectWarning asking user confirmation."""
        if self.env.context.get("account_unmerge_confirm"):
            return

        action = self.env["ir.actions.actions"]._for_xml_id(
            "account.action_unmerge_accounts",
        )
        msg = _("Are you sure? This will perform the following operations:\n")
        for account in self:
            msg += _(
                "Account %(account)s will be split in %(num_accounts)s, "
                "one for each company:\n",
                account=account.display_name,
                num_accounts=len(account.company_ids),
            )
            msg += "".join(
                f"    - {company.name}: {account.with_company(company).display_name}\n"
                for company in account.company_ids
            )
        raise RedirectWarning(
            msg,
            action,
            _("Unmerge"),
            additional_context={
                **self.env.context,
                "account_unmerge_confirm": True,
            },
        )

    def _action_unmerge(self):
        """Unmerge ``self`` into one account per company."""
        self.ensure_one()

        # Step 1: Check access rights.
        self._check_action_unmerge_possible()

        # Step 2: Create one new account per non-base company.
        base_company = (
            self.env.company
            if self.env.company in self.company_ids
            else self.company_ids[0]
        )
        new_account_by_company = self._unmerge_create_accounts(base_company)
        new_accounts = self.env["account.account"].union(
            *new_account_by_company.values(),
        )

        # Step 3: Repoint foreign keys in the DB from self to the new accounts.
        self.env.invalidate_all()
        # {company_id (as text): new_account_id}, matching the on-disk jsonb keys.
        new_account_id_by_company_id = {
            str(company.id): new_account.id
            for company, new_account in new_account_by_company.items()
        }
        (self | new_accounts).invalidate_recordset()

        self._unmerge_remap_many2x_fields(new_account_id_by_company_id)
        self._unmerge_remap_reference_fields(new_account_id_by_company_id)
        self._unmerge_remap_many2one_reference_fields(new_account_id_by_company_id)
        self._unmerge_migrate_company_dependent_fields(
            new_accounts, new_account_id_by_company_id
        )
        self._unmerge_split_xmlids(base_company, new_account_id_by_company_id)

        self.env.registry.clear_cache()
        self.env.invalidate_all()

        # Step 4: Reassign the original account to the base company only.
        self._unmerge_reassign_company_fields(base_company)

        # Step 5: Log in chatter.
        self._unmerge_log_split(new_accounts, base_company)

        return new_accounts

    def _unmerge_company_id_subquery(self, model):
        """Build a ``(id, company_id)`` subquery for *model*, or None."""
        if model == "res.company":
            company_id_field = "id"
        elif "company_id" in self.env[model]:
            company_id_field = "company_id"
        else:
            # No usable company column: signal the caller to skip this model.
            return None
        with contextlib.suppress(ValueError):
            query = Query(
                self.env,
                self.env[model]._table,
                self.env[model]._table_sql,
            )
            # Alias the columns id/company_id so the remap UPDATEs below can
            # reference them by name.
            return query.select(
                SQL(
                    "%s AS id",
                    self.env[model]._field_to_sql(query.table, "id"),
                ),
                SQL(
                    "%s AS company_id",
                    self.env[model]._field_to_sql(
                        query.table,
                        company_id_field,
                        query,
                    ),
                ),
            )

    def _unmerge_create_accounts(self, base_company):
        """Step 2: copy ``self`` once per non-base company, returning
        ``{company: new_account}``.
        """
        companies_to_update = self.company_ids - base_company
        check_company_fields = {
            fname
            for fname, field in self._fields.items()
            if field.relational and field.check_company
        }
        return {
            company: self.copy(
                default={
                    "name": self.name,
                    "company_ids": [Command.set(company.ids)],
                    # Keep only the check_company relational values that belong
                    # to this company.
                    **{
                        fname: self[fname].filtered(
                            lambda record, company=company: (
                                record.company_id == company
                            ),
                        )
                        for fname in check_company_fields
                    },
                }
            )
            for company in companies_to_update
        }

    def _unmerge_remap_many2x_fields(self, new_account_id_by_company_id):
        """Step 3.1: repoint stored many2one/many2many FKs and m2o
        company-dependent fields that point at ``self``."""
        new_account_id_by_company_id_json = json.dumps(new_account_id_by_company_id)
        many2x_fields = self.env["ir.model.fields"].search(
            [
                ("ttype", "in", ("many2one", "many2many")),
                ("relation", "=", "account.account"),
                ("store", "=", True),
                ("company_dependent", "=", False),
            ]
        )
        for field_to_update in many2x_fields:
            model = field_to_update.model
            if not self.env[model]._auto:
                continue
            if not (query_company_id := self._unmerge_company_id_subquery(model)):
                continue
            if field_to_update.ttype == "many2one":
                table = self.env[model]._table
                account_column = field_to_update.name
                model_column = "id"
            else:
                table = field_to_update.relation_table
                account_column = field_to_update.column2
                model_column = field_to_update.column1
            self.env.cr.execute(
                SQL(
                    """
                 UPDATE %(table)s
                    SET %(account_column)s = (
                            %(json)s::jsonb->>
                            table_with_company_id.company_id::text
                        )::int
                   FROM (%(query_company_id)s) table_with_company_id
                  WHERE table_with_company_id.id = %(model_column)s
                    AND %(table)s.%(account_column)s = %(account_id)s
                    AND table_with_company_id.company_id
                        IN %(company_ids_to_update)s
                """,
                    table=SQL.identifier(table),
                    account_column=SQL.identifier(account_column),
                    json=new_account_id_by_company_id_json,
                    query_company_id=query_company_id,
                    model_column=SQL.identifier(table, model_column),
                    account_id=self.id,
                    company_ids_to_update=tuple(
                        new_account_id_by_company_id,
                    ),
                )
            )
        for field in self.env.registry.many2one_company_dependents[self._name]:
            self.env.cr.execute(
                SQL(
                    """
                UPDATE %(table)s
                SET %(column)s = (
                    SELECT jsonb_object_agg(key,
                        CASE
                            WHEN value::int = %(account_id)s
                                AND %(json)s ? key
                            THEN (%(json)s::jsonb->>key)::int
                            ELSE value::int
                        END
                    )
                    FROM jsonb_each_text(%(column)s)
                )
                WHERE %(column)s IS NOT NULL
                """,
                    table=SQL.identifier(
                        self.env[field.model_name]._table,
                    ),
                    column=SQL.identifier(field.name),
                    json=new_account_id_by_company_id_json,
                    account_id=self.id,
                )
            )

    def _unmerge_remap_reference_fields(self, new_account_id_by_company_id):
        """Step 3.2: repoint stored Reference fields (``account.account,<id>``)."""
        new_account_id_by_company_id_json = json.dumps(new_account_id_by_company_id)
        reference_fields = self.env["ir.model.fields"].search(
            [
                ("ttype", "=", "reference"),
                ("store", "=", True),
            ]
        )
        for field_to_update in reference_fields:
            model = field_to_update.model
            if not self.env[model]._auto:
                continue
            if not (query_company_id := self._unmerge_company_id_subquery(model)):
                continue
            self.env.cr.execute(
                SQL(
                    """
                 UPDATE %(table)s
                    SET %(column)s = 'account.account,' || (
                        %(json)s::jsonb->>
                        table_with_company_id.company_id::text)
                   FROM (%(query_company_id)s) table_with_company_id
                  WHERE table_with_company_id.id = %(table)s.id
                    AND %(column)s = %(value_to_update)s
                    AND table_with_company_id.company_id
                        IN %(company_ids_to_update)s
                """,
                    table=SQL.identifier(self.env[model]._table),
                    column=SQL.identifier(field_to_update.name),
                    json=new_account_id_by_company_id_json,
                    query_company_id=query_company_id,
                    value_to_update=f"account.account,{self.id}",
                    company_ids_to_update=tuple(
                        new_account_id_by_company_id,
                    ),
                )
            )

    def _unmerge_remap_many2one_reference_fields(self, new_account_id_by_company_id):
        """Step 3.3: repoint stored Many2oneReference fields to ``account.account``."""
        new_account_id_by_company_id_json = json.dumps(new_account_id_by_company_id)
        many2one_reference_fields = self.env["ir.model.fields"].search(
            [
                ("ttype", "=", "many2one_reference"),
                ("store", "=", True),
                "!",
                "&",
                ("model", "=", "studio.approval.request"),
                ("name", "=", "res_id"),
            ]
        )
        for field_to_update in many2one_reference_fields:
            model = field_to_update.model
            model_field = (
                self.env[model]._fields[field_to_update.name]._related_model_field
            )
            if (
                not self.env[model]._auto
                or not self.env[model]._fields[model_field].store
            ):
                continue
            if not (query_company_id := self._unmerge_company_id_subquery(model)):
                continue
            self.env.cr.execute(
                SQL(
                    """
                 UPDATE %(table)s
                    SET %(column)s = (
                        %(json)s::jsonb->>
                        table_with_company_id.company_id::text)::int
                   FROM (%(query_company_id)s) table_with_company_id
                  WHERE table_with_company_id.id = %(table)s.id
                    AND %(column)s = %(account_id)s
                    AND %(model_column)s = 'account.account'
                    AND table_with_company_id.company_id
                        IN %(company_ids_to_update)s
                """,
                    table=SQL.identifier(self.env[model]._table),
                    column=SQL.identifier(field_to_update.name),
                    json=new_account_id_by_company_id_json,
                    query_company_id=query_company_id,
                    account_id=self.id,
                    model_column=SQL.identifier(model_field),
                    company_ids_to_update=tuple(
                        new_account_id_by_company_id,
                    ),
                )
            )

    def _unmerge_migrate_company_dependent_fields(
        self, new_accounts, new_account_id_by_company_id
    ):
        """Step 3.4: move each company's slice of company_dependent jsonb values
        onto the new account, then strip those slices from the original."""
        new_account_id_by_company_id_json = json.dumps(new_account_id_by_company_id)
        self.env.cr.execute(
            SQL(
                """
            WITH new_account_company AS (
                SELECT key AS company_id, value::int AS account_id
                FROM json_each_text(%(json)s)
            )
            UPDATE %(table)s new
            SET %(migrate_fields)s
            FROM %(table)s old, new_account_company a2c
            WHERE old.id = %(old_id)s
            AND a2c.account_id = new.id
            AND new.id IN %(new_ids)s
            """,
                json=new_account_id_by_company_id_json,
                table=SQL.identifier(self._table),
                migrate_fields=SQL(", ").join(
                    SQL(
                        """
                    %(field)s = CASE
                        WHEN old.%(field)s ? a2c.company_id
                        THEN jsonb_build_object(
                            a2c.company_id,
                            old.%(field)s->a2c.company_id)
                        ELSE NULL END
                    """,
                        field=SQL.identifier(field_name),
                    )
                    for field_name, field in self._fields.items()
                    if field.company_dependent
                ),
                old_id=self.id,
                new_ids=tuple(new_accounts.ids),
            )
        )
        # Remove values for other companies on original account
        self.env.cr.execute(
            SQL(
                "UPDATE %(table)s SET %(fields_drop)s WHERE id = %(id)s",
                table=SQL.identifier(self._table),
                fields_drop=SQL(", ").join(
                    SQL(
                        "%(field)s = NULLIF(%(field)s - "
                        "%(company_ids)s::text[], '{}'::jsonb)",
                        field=SQL.identifier(field_name),
                        company_ids=list(new_account_id_by_company_id),
                    )
                    for field_name, field in self._fields.items()
                    if field.company_dependent
                ),
                id=self.id,
            )
        )

    def _unmerge_split_xmlids(self, base_company, new_account_id_by_company_id):
        """Step 3.5: hand each company-prefixed xmlid to its unmerged account."""
        self.env["ir.model.data"].invalidate_model()
        account_id_by_company_id_json = json.dumps(
            {
                **new_account_id_by_company_id,
                str(base_company.id): self.id,
            }
        )
        self.env.cr.execute(
            SQL(
                """
             UPDATE ir_model_data
                SET res_id = (
                        %(json)s::jsonb->>
                        substring(name, %(xmlid_regex)s)
                    )::int
              WHERE module = 'account'
                AND model = 'account.account'
                AND res_id = %(account_id)s
                AND name ~ %(xmlid_regex)s
            """,
                json=account_id_by_company_id_json,
                xmlid_regex=r"([\d]+)_.*",
                account_id=self.id,
            )
        )

    def _unmerge_reassign_company_fields(self, base_company):
        """Step 4: pin the original account to ``base_company`` and keep only the
        check_company relational values that belong to it."""
        write_vals = {"company_ids": [Command.set(base_company.ids)]}
        check_company_fields = {
            field
            for field in self._fields.values()
            if field.relational and field.check_company
        }
        for field in check_company_fields:
            corecord = self[field.name]
            filtered_corecord = corecord.filtered_domain(
                corecord._check_company_domain(base_company),
            )
            write_vals[field.name] = (
                filtered_corecord.id
                if field.type == "many2one"
                else [Command.set(filtered_corecord.ids)]
            )
        self.write(write_vals)

    def _unmerge_log_split(self, new_accounts, base_company):
        """Step 5: note the split in each new account's chatter."""
        msg_body = _(
            "This account was split off from %(account_name)s (%(company_name)s).",
            account_name=self._get_html_link(title=self.display_name),
            company_name=base_company.name,
        )
        new_accounts._message_log_batch(
            bodies={a.id: msg_body for a in new_accounts},
        )


class AccountGroup(models.Model):
    _name = "account.group"
    _description = "Account Group"
    _order = "code_prefix_start"
    _check_company_auto = True
    _check_company_domain = models.check_company_domain_parent_of

    parent_id = fields.Many2one(
        "account.group",
        index=True,
        ondelete="cascade",
        readonly=True,
        check_company=True,
    )
    name = fields.Char(required=True, translate=True)
    code_prefix_start = fields.Char(
        compute="_compute_code_prefix_start",
        readonly=False,
        store=True,
        precompute=True,
    )
    code_prefix_end = fields.Char(
        compute="_compute_code_prefix_end",
        readonly=False,
        store=True,
        precompute=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        default=lambda self: self.env.company.root_id,
    )

    _check_length_prefix = models.Constraint(
        "CHECK(char_length(COALESCE(code_prefix_start, '')) "
        "= char_length(COALESCE(code_prefix_end, '')))",
        "The length of the starting and the ending code prefix must be the same",
    )

    @api.depends("code_prefix_start")
    def _compute_code_prefix_end(self):
        for group in self:
            if not group.code_prefix_end or (
                group.code_prefix_start
                and group.code_prefix_end < group.code_prefix_start
            ):
                group.code_prefix_end = group.code_prefix_start

    @api.depends("code_prefix_end")
    def _compute_code_prefix_start(self):
        for group in self:
            if not group.code_prefix_start or (
                group.code_prefix_end
                and group.code_prefix_start > group.code_prefix_end
            ):
                group.code_prefix_start = group.code_prefix_end

    @api.depends("code_prefix_start", "code_prefix_end")
    def _compute_display_name(self):
        for group in self:
            prefix = group.code_prefix_start and str(group.code_prefix_start)
            if prefix and group.code_prefix_end != group.code_prefix_start:
                prefix += "-" + str(group.code_prefix_end)
            group.display_name = " ".join(
                filter(None, [prefix, group.name]),
            )

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
        if operator == "ilike" and isinstance(value, str):
            return [
                "|",
                ("code_prefix_start", "=ilike", value + "%"),
                ("name", operator, value),
            ]
        return [("name", operator, value)]

    @api.constrains("code_prefix_start", "code_prefix_end")
    def _constraint_prefix_overlap(self):
        self.flush_model()
        query = """
            SELECT other.id FROM account_group this
            JOIN account_group other
              ON char_length(other.code_prefix_start)
                 = char_length(this.code_prefix_start)
             AND other.id != this.id
             AND other.company_id = this.company_id
             AND (
                other.code_prefix_start <= this.code_prefix_start
                AND this.code_prefix_start <= other.code_prefix_end
                OR
                other.code_prefix_start >= this.code_prefix_start
                AND this.code_prefix_end >= other.code_prefix_start
            )
            WHERE this.id = ANY(%(ids)s)
        """
        self.env.cr.execute(query, {"ids": list(self.ids)})
        res = self.env.cr.fetchall()
        if res:
            raise ValidationError(
                _("Account Groups with the same granularity can't overlap"),
            )

    def _sanitize_vals(self, vals):
        # Return a sanitized copy; never mutate the caller's dict in place.
        vals = dict(vals)
        if (
            vals.get("code_prefix_start")
            and "code_prefix_end" in vals
            and not vals["code_prefix_end"]
        ):
            del vals["code_prefix_end"]
        if (
            vals.get("code_prefix_end")
            and "code_prefix_start" in vals
            and not vals["code_prefix_start"]
        ):
            del vals["code_prefix_start"]
        return vals

    @api.constrains("parent_id")
    def _check_parent_not_circular(self):
        if self._has_cycle():
            raise ValidationError(
                _("You cannot create recursive groups."),
            )

    @api.model_create_multi
    def create(self, vals_list):
        groups = super().create([self._sanitize_vals(vals) for vals in vals_list])
        groups._adapt_parent_account_group()
        return groups

    def write(self, vals):
        res = super().write(self._sanitize_vals(vals))
        if "code_prefix_start" in vals or "code_prefix_end" in vals:
            self._adapt_parent_account_group()
        return res

    def unlink(self):
        # Reparent every child onto its grandparent with a single search and
        # one write per distinct parent, instead of a search+write per record.
        children = self.env["account.group"].search(
            [("parent_id", "in", self.ids)],
        )
        for parent, group_children in children.grouped("parent_id").items():
            group_children.parent_id = parent.parent_id.id
        return super().unlink()

    def _adapt_parent_account_group(self, company=None):
        """Ensure consistency of the hierarchy of account groups."""
        if self.env.context.get("delay_account_group_sync"):
            return

        company_ids = company.ids if company else self.company_id.ids
        if not company_ids:
            return

        self.flush_model()
        query = SQL(
            """
            WITH relation AS (
                SELECT DISTINCT ON (child.id)
                       child.id AS child_id,
                       parent.id AS parent_id
                  FROM account_group parent
            RIGHT JOIN account_group child
                    ON char_length(parent.code_prefix_start)
                       < char_length(child.code_prefix_start)
                   AND parent.code_prefix_start
                       <= LEFT(child.code_prefix_start,
                               char_length(parent.code_prefix_start))
                   AND parent.code_prefix_end
                       >= LEFT(child.code_prefix_end,
                               char_length(parent.code_prefix_end))
                   AND parent.id != child.id
                   AND parent.company_id = child.company_id
                 WHERE child.company_id = ANY(%s)
              ORDER BY child.id,
                       char_length(parent.code_prefix_start) DESC
            )
            UPDATE account_group child
               SET parent_id = relation.parent_id
              FROM relation
             WHERE child.id = relation.child_id
               AND child.parent_id IS DISTINCT FROM relation.parent_id
         RETURNING child.id
        """,
            list(company_ids),
        )
        self.env.cr.execute(query)

        updated_rows = self.env.cr.fetchall()
        if updated_rows:
            self.invalidate_model(["parent_id"])
