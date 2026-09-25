import json

from odoo import api, fields, models
from odoo.libs.debug_log import DebugLog
from odoo.tools import SQL

_debug = DebugLog(__name__)


class AccountTaxMergeWizard(models.TransientModel):
    _name = "account.tax.merge.wizard"
    _inherit = ["mixin.account.merge"]
    _description = "Tax merge wizard"

    _merge_model = "account.tax"
    _merge_records_field = "tax_ids"

    tax_ids = fields.Many2many(comodel_name="account.tax")
    wizard_line_ids = fields.One2many(
        comodel_name="account.tax.merge.wizard.line",
        inverse_name="wizard_id",
        compute="_compute_wizard_line_ids",
        store=True,
        readonly=False,
    )

    def _get_merge_messages(self):
        return {
            "wrong_model": self.env._("This can only be used on taxes."),
            "too_few": self.env._("You must select at least 2 taxes."),
            "merged": self.env._("Taxes successfully merged!"),
        }

    @api.model
    def _get_grouping_key(self, tax):
        return (
            tax.name,
            tax.type_tax_use,
            tax.tax_scope,
            tax.country_id,
            tax.amount_type,
            tax.amount,
            tax.price_include_override,
            tax.include_base_amount,
            tax.is_base_affected,
            tax.active,
        )

    @api.model
    def _get_repartition_signature(self, tax):
        return tuple(
            (
                line.document_type,
                line.repartition_type,
                line.factor_percent,
                line.account_id.id,
                tuple(sorted(line.tag_ids.ids)),
            )
            for line in tax.repartition_line_ids.sorted(
                lambda line: (
                    line.document_type,
                    line.repartition_type,
                    line.sequence,
                    line.factor_percent,
                    line.account_id.id or 0,
                )
            )
        )

    @api.depends("tax_ids")
    def _compute_wizard_line_ids(self):
        super()._compute_wizard_line_ids()

    def _get_merge_tables_excluded(self, model):
        return super()._get_merge_tables_excluded(model) | {
            self.env["account.tax.repartition.line"]._table
        }

    @api.model
    def _repoint_repartition_lines(self, taxes_to_remove, tax_to_merge_into):

        def ordered(tax):
            return tax.repartition_line_ids._sorted_for_positional_pairing()

        destination = ordered(tax_to_merge_into)
        mapping = {}
        for tax in taxes_to_remove:
            for old, new in zip(ordered(tax), destination, strict=True):
                mapping[old.id] = new.id
        if not mapping:
            return
        self.env["account.move.line"].flush_model(["tax_repartition_line_id"])
        self.env.cr.execute(
            SQL(
                """
                UPDATE account_move_line
                   SET tax_repartition_line_id =
                       (%(mapping)s::jsonb->>tax_repartition_line_id::text)::int
                 WHERE tax_repartition_line_id IN %(old_ids)s
                """,
                mapping=json.dumps({str(k): v for k, v in mapping.items()}),
                old_ids=tuple(mapping),
            )
        )
        self.env["account.move.line"].invalidate_model(["tax_repartition_line_id"])

    @api.model
    def _prepare_merge(self, taxes):
        self._repoint_repartition_lines(taxes[1:], taxes[0])


class AccountTaxMergeWizardLine(models.TransientModel):
    _name = "account.tax.merge.wizard.line"
    _inherit = ["mixin.account.merge.line"]
    _description = "Tax merge wizard line"
    _order = "sequence, id"

    _merge_record_field = "tax_id"
    _merge_record_display_type = "tax"
    _merge_record_hashed_field = "tax_has_hashed_entries"

    wizard_id = fields.Many2one(
        comodel_name="account.tax.merge.wizard",
        required=True,
        ondelete="cascade",
    )
    display_type = fields.Selection(
        selection=[("line_section", "Section"), ("tax", "Tax")],
        required=True,
    )
    tax_id = fields.Many2one(
        comodel_name="account.tax",
        readonly=True,
        ondelete="cascade",
    )
    company_ids = fields.Many2many(related="tax_id.company_ids")
    tax_has_hashed_entries = fields.Boolean(compute="_compute_tax_has_hashed_entries")

    @api.depends("tax_id")
    @_debug.perf.timed
    def _compute_tax_has_hashed_entries(self):
        hashed_lines = (
            self.env["account.move.line"]
            .sudo()
            ._read_group(
                [
                    ("move_id.inalterable_hash", "!=", False),
                    "|",
                    ("tax_line_id", "in", self.tax_id.ids),
                    ("tax_ids", "in", self.tax_id.ids),
                ],
                ["tax_line_id", "tax_ids"],
            )
        )
        hashed = {tax.id for taxes in hashed_lines for tax in taxes}
        _debug.perf.count("hashed_taxes_fetched", rows=len(hashed))
        for line in self:
            line.tax_has_hashed_entries = line.tax_id.id in hashed

    @api.depends("tax_id", "wizard_id.wizard_line_ids.is_selected", "display_type")
    def _compute_info(self):
        super()._compute_info()

    def _get_merge_section_name(self):
        return self.tax_id.display_name

    def _update_info_conflicts(self):
        self._update_info_company_conflict()
        self._update_info_repartition_conflict()
        self._update_info_hashed_moves_conflict()

    def _update_info_repartition_conflict(self):
        reference = None
        signature_of = self.wizard_id._get_repartition_signature
        for line in self:
            if not line.is_selected or line.info:
                continue
            signature = signature_of(line.tax_id)
            if reference is None:
                reference = (signature, line.tax_id)
            elif signature != reference[0]:
                line.info = self.env._(
                    "Its distribution differs from %s.",
                    reference[1].display_name,
                )
