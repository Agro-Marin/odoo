from odoo import models
from odoo.tools import float_compare


class AccountMoveLine(models.Model):
    "Inherit AccountMoveLine"

    _inherit = "account.move.line"

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _stock_account_get_anglo_saxon_price_unit(self):
        self.ensure_one()
        price_unit = super()._stock_account_get_anglo_saxon_price_unit()
        so_line = self.sale_line_ids and self.sale_line_ids[-1] or False
        move_is_downpayment = self.env.context.get("move_is_downpayment")
        if move_is_downpayment is None:
            move_is_downpayment = self.move_id.invoice_line_ids.filtered(
                lambda line: any(line.sale_line_ids.mapped("is_downpayment"))
            )
        if so_line:
            is_line_reversing = False
            if self.move_id.move_type == "out_refund" and not move_is_downpayment:
                is_line_reversing = True
            qty_to_invoice = self.product_uom_id._compute_quantity(
                self.quantity, self.product_id.uom_id
            )
            if self.move_id.move_type == "out_refund" and move_is_downpayment:
                qty_to_invoice = -qty_to_invoice
            account_moves = so_line.invoice_line_ids.move_id.filtered(
                lambda m: m.state == "posted"
                and bool(m.reversed_entry_id) == is_line_reversing
            )

            posted_cogs = self.env["account.move.line"].search(
                [
                    ("move_id", "in", account_moves.ids),
                    ("display_type", "=", "cogs"),
                    ("product_id", "=", self.product_id.id),
                    ("balance", ">", 0),
                ]
            )
            posted_cogs = posted_cogs.filtered(
                lambda l: so_line in l.cogs_origin_id.sale_line_ids
            )
            qty_invoiced = 0
            product_uom = self.product_id.uom_id
            for line in posted_cogs:
                if (
                    float_compare(
                        line.quantity, 0, precision_rounding=product_uom.rounding
                    )
                    and line.move_id.move_type == "out_refund"
                    and any(
                        line.move_id.invoice_line_ids.sale_line_ids.mapped(
                            "is_downpayment"
                        )
                    )
                ):
                    qty_invoiced += line.product_uom_id._compute_quantity(
                        abs(line.quantity), line.product_id.uom_id
                    )
                else:
                    qty_invoiced += line.product_uom_id._compute_quantity(
                        line.quantity, line.product_id.uom_id
                    )
            value_invoiced = sum(posted_cogs.mapped("balance"))
            reversal_moves = self.env["account.move"]._search(
                [("reversed_entry_id", "in", posted_cogs.move_id.ids)]
            )
            reversal_cogs = self.env["account.move.line"].search(
                [
                    ("move_id", "in", reversal_moves),
                    ("display_type", "=", "cogs"),
                    ("product_id", "=", self.product_id.id),
                    ("balance", ">", 0),
                ]
            )
            for line in reversal_cogs:
                if (
                    float_compare(
                        line.quantity, 0, precision_rounding=product_uom.rounding
                    )
                    and line.move_id.move_type == "out_refund"
                    and any(
                        line.move_id.invoice_line_ids.sale_line_ids.mapped(
                            "is_downpayment"
                        )
                    )
                ):
                    qty_invoiced -= line.product_uom_id._compute_quantity(
                        abs(line.quantity), line.product_id.uom_id
                    )
                else:
                    qty_invoiced -= line.product_uom_id._compute_quantity(
                        line.quantity, line.product_id.uom_id
                    )
            value_invoiced -= sum(reversal_cogs.mapped("balance"))

            product = self.product_id.with_company(self.company_id).with_context(
                value_invoiced=value_invoiced
            )
            average_price_unit = product._compute_average_price(
                qty_invoiced,
                qty_to_invoice,
                so_line.move_ids,
                is_returned=is_line_reversing,
            )
            price_unit = self.product_id.uom_id.with_company(
                self.company_id
            )._compute_price(average_price_unit, self.product_uom_id)
        return price_unit

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _sale_can_be_reinvoice(self):
        self.ensure_one()
        return (
            self.move_type != "entry"
            and self.display_type != "cogs"
            and super()._sale_can_be_reinvoice()
        )
