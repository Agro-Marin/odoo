from odoo import _, api, models
from odoo.exceptions import UserError


class AccountTax(models.Model):
    _name = "account.tax"
    _inherit = ["account.tax", "pos.load.mixin"]

    def write(self, vals):
        forbidden_fields = {
            "amount_type",
            "amount",
            "type_tax_use",
            "tax_group_id",
            "price_include",
            "price_include_override",
            "include_base_amount",
            "is_base_affected",
        }
        if forbidden_fields & set(vals.keys()) and self.ids:
            # Restrict to the taxes' own companies (multi-company safe) and check
            # for existence via the m2m relation table instead of reading the
            # tax_ids of every open-session order line across all companies.
            self.env["pos.order.line"].flush_model(["tax_ids"])
            self.env.cr.execute(
                """
                SELECT 1
                FROM account_tax_pos_order_line_rel AS rel
                JOIN pos_order_line AS line ON line.id = rel.pos_order_line_id
                JOIN pos_order AS o ON o.id = line.order_id
                JOIN pos_session AS s ON s.id = o.session_id
                WHERE rel.account_tax_id = ANY(%s)
                  AND o.company_id = ANY(%s)
                  AND s.state != 'closed'
                LIMIT 1
                """,
                [list(self.ids), list(self.company_id.ids)],
            )
            if self.env.cr.fetchone():
                raise UserError(
                    _(
                        "It is forbidden to modify a tax used in a POS order not posted. "
                        "You must close the POS sessions before modifying the tax."
                    )
                )
        return super().write(vals)

    # NOTE: no `_hook_compute_is_used` override. `account.tax.is_used` (which
    # gates deletion via `unlink_except_tax_used`) must reflect *finalized*
    # accounting only. All posted POS accounting already lands in
    # account.move.line — the combined session-closing move sets `tax_ids` on
    # its sale lines (pos_session._get_sale_vals) and invoiced orders carry the
    # tax on their invoice lines — so the base `_compute_is_used` scan of
    # account_move_line_account_tax_rel covers every closed/invoiced POS order.
    # A tax referenced only by a *non-posted* pos.order.line (draft/open
    # session) must stay deletable: the order degrades gracefully (the m2m link
    # cascades away and the closing entry is computed without it). Mutation of
    # such a tax is still blocked by `write` above until the session closes.

    @api.model
    def _load_pos_data_domain(self, data, config):
        return self.env["account.tax"]._check_company_domain(config.company_id.id)

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            "id",
            "name",
            "price_include",
            "include_base_amount",
            "is_base_affected",
            "has_negative_factor",
            "amount_type",
            "children_tax_ids",
            "amount",
            "company_id",
            "sequence",
            "tax_group_id",
            "fiscal_position_ids",
        ]
