from odoo import api, fields, models
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class AccountFiscalPosition(models.Model):
    _inherit = "account.fiscal.position"

    account_ids = fields.One2many(
        comodel_name="account.fiscal.position.account",
        inverse_name="position_id",
        string="Account Mapping",
        copy=True,
    )
    account_map = fields.Binary(compute="_compute_account_map")
    foreign_vat_header_mode = fields.Selection(
        selection=[
            ("templates_found", "Templates Found"),
            ("no_template", "No Template"),
        ],
        compute="_compute_foreign_vat_header_mode",
    )

    @_debug.perf.timed
    def _invalidate_company_configs(self):
        super()._invalidate_company_configs()
        self.env["account.config"].invalidate_model(["account_enabled_tax_country_ids"])

    @api.depends("foreign_vat", "country_id", "company_id")
    @_debug.perf.timed
    def _compute_foreign_vat_header_mode(self):
        AccountTax = self.env["account.tax"]
        country_taxes = AccountTax.search(
            [
                *AccountTax._check_company_domain(self.company_id),
                ("country_id", "in", self.country_id.ids),
            ]
        )
        for fiscal_position in self:
            if (
                not fiscal_position.foreign_vat
                or not fiscal_position.country_id
                or country_taxes.filtered_domain(
                    [("country_id", "=", fiscal_position.country_id.id)]
                ).filtered_domain(
                    AccountTax._check_company_domain(fiscal_position.company_id)
                )
            ):
                fiscal_position.foreign_vat_header_mode = False
            else:
                template = self._get_foreign_tax_chart_template(
                    fiscal_position.country_id
                )
                fiscal_position.foreign_vat_header_mode = (
                    "templates_found" if template["installed"] else "no_template"
                )

    @api.depends("account_ids.account_src_id", "account_ids.account_dest_id")
    def _compute_account_map(self):
        for position in self:
            position.account_map = {
                al.account_src_id.id: al.account_dest_id.id
                for al in position.account_ids
            }

    def _get_foreign_tax_chart_template(self, country):
        chart_template = self.env["account.chart.template"]
        template_code = chart_template._guess_chart_template(country)
        return chart_template._get_chart_template_mapping()[template_code]

    def map_account(self, account):
        if not self:
            return account
        self.check_singleton()
        account_map = self.account_map or {}
        return self.env["account.account"].browse(
            account_map.get(account._origin.id or account.id, account.id)
        )

    @_debug.perf.timed
    def action_view_related_taxes(self):
        _debug.lifecycle("action_view_related_taxes", records=self)
        list_view = self.env.ref(
            "account.account_tax_fiscal_position_view_tree", raise_if_not_found=False
        )
        domain = [
            *self.env["account.tax"]._check_company_domain(self.company_id),
            "|",
            ("id", "in", self.tax_ids.ids),
            ("fiscal_position_ids", "=", False),
        ]
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("%s taxes", self.display_name),
            "res_model": "account.tax",
            "views": [(list_view.id if list_view else False, "list"), (False, "form")],
            "domain": domain,
            "context": {"active_test": False},
        }

    @_debug.perf.timed
    def action_create_foreign_taxes(self):
        _debug.lifecycle("action_create_foreign_taxes", records=self)
        self.check_singleton()
        template = self._get_foreign_tax_chart_template(self.country_id)
        if not template["installed"]:
            localization_module = self.env["ir.module.module"].search(
                [("name", "=", template["module"])]
            )
            localization_module.sudo().button_immediate_install()
        created_records = self.env["account.chart.template"]._instantiate_foreign_taxes(
            self.country_id, self.company_id
        )
        created_records.get(
            "account.tax", self.env["account.tax"]
        ).fiscal_position_ids += self
