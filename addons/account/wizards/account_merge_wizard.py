import json

from odoo import api, fields, models
from odoo.libs.debug_log import DebugLog
from odoo.tools import SQL

_debug = DebugLog(__name__)


class AccountMergeWizard(models.TransientModel):
    _name = "account.merge.wizard"
    _inherit = ["mixin.account.merge"]
    _description = "Account merge wizard"

    _merge_model = "account.account"
    _merge_records_field = "account_ids"

    account_ids = fields.Many2many(comodel_name="account.account")
    is_group_by_name = fields.Boolean(
        string="Group by name?",
        default=False,
        help="Tick this checkbox if you want accounts to be grouped by name for merging.",
    )
    wizard_line_ids = fields.One2many(
        comodel_name="account.merge.wizard.line",
        inverse_name="wizard_id",
        compute="_compute_wizard_line_ids",
        store=True,
        readonly=False,
    )

    def _get_merge_messages(self):
        return {
            "wrong_model": self.env._("This can only be used on accounts."),
            "too_few": self.env._("You must select at least 2 accounts."),
            "merged": self.env._("Accounts successfully merged!"),
        }

    def _get_grouping_key(self, account):
        self.check_singleton()
        grouping_fields = [
            "account_type",
            "non_trade",
            "currency_id",
            "reconcile",
            "active",
        ]
        if self.is_group_by_name:
            grouping_fields.append("name")
        return tuple(account[field] for field in grouping_fields)

    def _get_mergeable_records(self):
        return (
            super()
            ._get_mergeable_records()
            .filtered(lambda a: a.account_type not in ("asset_bank", "asset_cash"))
        )

    @api.depends("is_group_by_name", "account_ids")
    def _compute_wizard_line_ids(self):
        super()._compute_wizard_line_ids()

    @api.model
    def _prepare_merge(self, accounts):
        return self.env.execute_query(
            SQL(
                """
            SELECT jsonb_object_agg(key, value)
              FROM account_account, jsonb_each_text(account_account.code_store)
             WHERE account_account.id IN %(account_ids)s
            """,
                account_ids=tuple(accounts.ids),
                to_flush=accounts._fields["code_store"],
            )
        )[0][0]

    @api.model
    def _finalize_merge(self, account, companies, code_by_company):
        self.env.cr.execute(
            SQL(
                """
            UPDATE account_account
               SET code_store = %(code_by_company_json)s
             WHERE id = %(account_to_merge_into_id)s
            """,
                code_by_company_json=json.dumps(code_by_company),
                account_to_merge_into_id=account.id,
            )
        )
        _debug.perf.count("merged_account_codes_written", rows=self.env.cr.rowcount)
        super()._finalize_merge(account, companies, code_by_company)
        self.env.add_to_compute(self.env["account.account"]._fields["tag_ids"], account)


class AccountMergeWizardLine(models.TransientModel):
    _name = "account.merge.wizard.line"
    _inherit = ["mixin.account.merge.line"]
    _description = "Account merge wizard line"
    _order = "sequence, id"

    _merge_record_field = "account_id"
    _merge_record_display_type = "account"
    _merge_record_hashed_field = "account_has_hashed_entries"

    wizard_id = fields.Many2one(
        comodel_name="account.merge.wizard",
        required=True,
        ondelete="cascade",
    )
    display_type = fields.Selection(
        selection=[
            ("line_section", "Section"),
            ("line_subsection", "Subsection"),
            ("account", "Account"),
        ],
        required=True,
    )
    account_id = fields.Many2one(
        comodel_name="account.account",
        readonly=True,
        ondelete="cascade",
    )
    company_ids = fields.Many2many(
        related="account_id.company_ids",
        string="Companies",
    )
    account_has_hashed_entries = fields.Boolean(
        compute="_compute_account_has_hashed_entries"
    )

    @api.depends("account_id")
    @_debug.perf.timed
    def _compute_account_has_hashed_entries(self):
        query = self.env["account.move.line"]._search(
            [
                ("account_id", "in", self.account_id.ids),
                ("move_id.inalterable_hash", "!=", False),
            ],
            bypass_access=True,
        )
        query_result = self.env.execute_query(
            query.select(SQL("DISTINCT account_move_line.account_id"))
        )
        _debug.perf.count("hashed_entry_accounts_fetched", rows=len(query_result))
        accounts_with_hashed_entries_ids = {r[0] for r in query_result}
        wizard_lines_with_hashed_entries = self.filtered(
            lambda l: l.account_id.id in accounts_with_hashed_entries_ids
        )
        wizard_lines_with_hashed_entries.account_has_hashed_entries = True
        (self - wizard_lines_with_hashed_entries).account_has_hashed_entries = False

    @api.depends("account_id", "wizard_id.wizard_line_ids.is_selected", "display_type")
    def _compute_info(self):
        super()._compute_info()

    @_debug.perf.timed
    def _get_merge_section_name(self):
        self.check_singleton()

        account_type_label = dict(
            self.pool["account.account"].account_type._description_selection(self.env)
        )[self.account_id.account_type]
        if self.account_id.account_type in ["asset_receivable", "liability_payable"]:
            account_type_label = (
                self.env._("Non-trade %s", account_type_label)
                if self.account_id.non_trade
                else self.env._("Trade %s", account_type_label)
            )

        other_name_elements = []
        if self.account_id.currency_id:
            other_name_elements.append(self.account_id.currency_id.name)

        if self.account_id.reconcile:
            other_name_elements.append(self.env._("Reconcilable"))

        if not self.account_id.active:
            other_name_elements.append(self.env._("Deprecated"))

        if not self.wizard_id.is_group_by_name:
            grouping_key_name = account_type_label
            if other_name_elements:
                grouping_key_name = (
                    f"{grouping_key_name} ({', '.join(other_name_elements)})"
                )
        else:
            grouping_key_name = f"{self.account_id.name} ({', '.join([account_type_label] + other_name_elements)})"

        return grouping_key_name
