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

    def _hook_compute_is_used(self, tax_to_compute):
        # OVERRIDE: count a tax referenced by any pos.order.line as used, so it
        # cannot be deleted while a POS order still carries it. Mirrors the
        # write() guard above (which blocks *modifying* such a tax): without
        # this, a tax used only by an open-session order stayed deletable, and
        # deleting it left the session-closing entry computed without a tax that
        # was already collected from the customer — a fiscal under-declaration.
        # Archiving is the supported way to retire a tax that is in use.
        used_taxes = super()._hook_compute_is_used(tax_to_compute)
        tax_to_compute -= used_taxes
        if tax_to_compute:
            self.env["pos.order.line"].flush_model(["tax_ids"])
            # `= ANY(%s)` + a list, not `IN %s` + tuple: the latter is psycopg2-only
            # and raises a syntax error under this fork's psycopg3. Scanning the m2m
            # relation directly is equivalent to and cheaper than a correlated EXISTS.
            self.env.cr.execute(
                """
                SELECT DISTINCT account_tax_id
                FROM account_tax_pos_order_line_rel
                WHERE account_tax_id = ANY(%s)
                """,
                [list(tax_to_compute)],
            )
            used_taxes.update(tax[0] for tax in self.env.cr.fetchall())
        return used_taxes

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
