from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL


class PurchaseBillLineMatch(models.Model):
    _name = "purchase.bill.line.match"
    _description = "Purchase Order Line & Vendor Bill Line Matching"
    _auto = False
    _order = "product_id, aml_id, pol_id"


    company_id = fields.Many2one(
        comodel_name="res.company",
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        readonly=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        related="product_id.uom_id",
        comodel_name="uom.uom",
    )

    pol_id = fields.Many2one(
        comodel_name="purchase.order.line",
        readonly=True,
    )
    purchase_order_id = fields.Many2one(
        comodel_name="purchase.order",
        readonly=True,
    )
    aml_id = fields.Many2one(
        comodel_name="account.move.line",
        readonly=True,
    )
    account_move_id = fields.Many2one(
        comodel_name="account.move",
        readonly=True,
    )

    state = fields.Char(
        readonly=True,
    )
    reference = fields.Char(
        compute="_compute_reference",
    )

    line_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        readonly=True,
    )
    line_qty = fields.Float(
        readonly=True,
    )
    qty_invoiced = fields.Float(
        readonly=True,
    )
    qty_to_invoice = fields.Float(
        string="Qty to invoice",
        readonly=True,
    )
    product_uom_qty = fields.Float(
        compute="_compute_product_uom_qty",
        readonly=False,
        inverse="_inverse_product_uom_qty",
    )

    product_uom_price = fields.Float(
        compute="_compute_product_uom_price",
        readonly=False,
        inverse="_inverse_product_uom_price",
    )
    line_amount_taxexc = fields.Monetary(
        readonly=True,
    )
    billed_amount_taxexc = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_amount_untaxed_fields",
    )
    purchase_amount_taxexc = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_amount_untaxed_fields",
    )


    def _compute_amount_untaxed_fields(self):
        for line in self:
            line.billed_amount_taxexc = (
                line.line_amount_taxexc if line.account_move_id else False
            )
            line.purchase_amount_taxexc = (
                line.line_amount_taxexc if line.purchase_order_id else False
            )

    def _compute_reference(self):
        for line in self:
            line.reference = (
                line.purchase_order_id.display_name or line.account_move_id.display_name
            )

    def _compute_display_name(self):
        for line in self:
            line.display_name = (
                line.product_id.display_name or line.aml_id.name or line.pol_id.name
            )

    def _compute_product_uom_qty(self):
        for line in self:
            if line.product_id:
                line.product_uom_qty = line.line_uom_id._compute_quantity(
                    line.line_qty, line.product_uom_id
                )
            else:
                line.product_uom_qty = line.line_qty

    @api.depends("aml_id.price_unit", "pol_id.price_unit")
    def _compute_product_uom_price(self):
        for line in self:
            line.product_uom_price = (
                line.aml_id.price_unit if line.aml_id else line.pol_id.price_unit
            )


    @api.onchange("product_uom_price")
    def _inverse_product_uom_price(self):
        for line in self:
            if line.aml_id:
                line.aml_id.price_unit = line.product_uom_price
            else:
                line.pol_id.price_unit = line.product_uom_price

    @api.onchange("product_uom_qty")
    def _inverse_product_uom_qty(self):
        for line in self:
            if line.aml_id:
                line.aml_id.quantity = line.product_uom_qty
            else:
                previous_price_unit = line.pol_id.price_unit
                line.pol_id.product_qty = line.product_uom_qty
                line.pol_id.price_unit = previous_price_unit


    def action_open_line(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move" if self.account_move_id else "purchase.order",
            "view_mode": "form",
            "res_id": (
                self.account_move_id.id
                if self.account_move_id
                else self.purchase_order_id.id
            ),
        }

    @api.model
    def _action_create_bill_from_po_lines(self, partner, po_lines):
        if len(po_lines.currency_id) == 1:
            currency = po_lines.currency_id
        elif len(po_lines.company_id) == 1:
            currency = po_lines.company_id.currency_id
        else:
            currency = self.env.company.currency_id
        bill = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": partner.id,
                "currency_id": currency.id,
            }
        )
        bill._add_purchase_order_lines(po_lines)
        return bill._get_records_action()

    def action_match_lines(self):
        if not self.pol_id:
            raise UserError(
                _(
                    "You must select at least one Purchase Order line to match or create bill."
                )
            )
        if (
            not self.aml_id
        ):
            return self._action_create_bill_from_po_lines(self.partner_id, self.pol_id)

        pol_by_product = self.pol_id.grouped("product_id")
        aml_by_product = self.aml_id.grouped("product_id")
        residual_purchase_order_lines = self.pol_id
        residual_account_move_lines = self.aml_id

        for product, po_lines in pol_by_product.items():
            matching_bill_lines = aml_by_product.get(product)
            if not matching_bill_lines:
                continue

            if len(po_lines) <= 1:
                po_line = po_lines[0]
                matching_bill_lines.purchase_line_ids = [Command.link(po_line.id)]
                residual_purchase_order_lines -= po_line
                residual_account_move_lines -= matching_bill_lines
            else:
                remaining_po = list(po_lines)
                remaining_aml = list(matching_bill_lines)

                for pol in list(remaining_po):
                    currency = (
                        pol.currency_id
                        or pol.company_id.currency_id
                        or self.env.company.currency_id
                    )
                    for aml in list(remaining_aml):
                        if (
                            currency.compare_amounts(aml.price_unit, pol.price_unit)
                            == 0
                        ):
                            aml.purchase_line_ids = [Command.link(pol.id)]
                            residual_purchase_order_lines -= pol
                            residual_account_move_lines -= aml
                            remaining_po.remove(pol)
                            remaining_aml.remove(aml)
                            break

                for pol, aml in zip(
                    list(remaining_po), list(remaining_aml), strict=False
                ):
                    aml.purchase_line_ids = [Command.link(pol.id)]
                    residual_purchase_order_lines -= pol
                    residual_account_move_lines -= aml

        if len(residual_bill := self.aml_id.move_id) == 1:
            if residual_account_move_lines:
                residual_account_move_lines.unlink()

            residual_bill._add_purchase_order_lines(residual_purchase_order_lines)
        return None

    def action_add_to_po(self):
        if not self or not self.aml_id:
            raise UserError(_("Select Vendor Bill lines to add to a Purchase Order"))
        partner = self.mapped("partner_id.commercial_partner_id")
        if len(partner) > 1:
            raise UserError(_("Please select bill lines with the same vendor."))
        context = {
            "default_partner_id": partner.id,
            "dialog_size": "medium",
            "has_products": bool(self.aml_id.product_id),
        }
        if len(self.purchase_order_id) > 1:
            raise UserError(
                _("Vendor Bill lines can only be added to one Purchase Order.")
            )
        if self.purchase_order_id:
            context["default_purchase_order_id"] = self.purchase_order_id.id
        return {
            "type": "ir.actions.act_window",
            "name": _("Add to Purchase Order"),
            "res_model": "bill.to.po.wizard",
            "target": "new",
            "views": [(self.env.ref("purchase.bill_to_po_wizard_form").id, "form")],
            "context": context,
        }


    @property
    def _table_query(self):
        return SQL(
            "%s UNION ALL %s",
            self._query_po_line(),
            self._query_am_line(),
        )

    @api.model
    def _query_po_line(self):
        return SQL(
            """
            SELECT
                %s
            FROM
                %s
            WHERE
                %s
            """,
            self._select_po_line(),
            self._from_po_line(),
            self._where_po_line(),
        )

    @api.model
    def _select_po_line(self):
        return SQL(
            """
            pol.id,
            pol.id AS pol_id,
            NULL::INTEGER AS aml_id,
            pol.company_id,
            pol.partner_id,
            pol.product_id,
            pol.product_qty AS line_qty,
            pol.product_uom_id AS line_uom_id,
            pol.qty_invoiced,
            pol.qty_to_invoice,
            po.id AS purchase_order_id,
            NULL::INTEGER AS account_move_id,
            pol.price_subtotal AS line_amount_taxexc,
            po.currency_id,
            po.state
            """,
        )

    @api.model
    def _from_po_line(self):
        return SQL(
            """
            purchase_order_line pol
            LEFT JOIN purchase_order po ON pol.order_id = po.id
            """,
        )

    @api.model
    def _where_po_line(self):
        return SQL(
            """
            (
                po.state = 'done'
                AND (
                    -- Lines with pending qty to invoice (includes partially invoiced
                    -- and delivery-policy lines before receipt)
                    (
                        (pol.product_qty > pol.qty_invoiced OR pol.qty_to_invoice > 0)
                        AND NOT EXISTS (
                            SELECT 1 FROM account_move_line_purchase_order_line_rel rel
                            JOIN account_move_line aml ON rel.move_line_id = aml.id
                            WHERE rel.order_line_id = pol.id
                            AND aml.parent_state = 'draft'
                        )
                    )
                    -- OR over-invoiced lines needing credit notes
                    OR pol.qty_to_invoice < 0
                )
            )
            OR (COALESCE(pol.display_type, '') = '' AND pol.is_downpayment AND pol.qty_invoiced > 0)
            """,
        )

    @api.model
    def _query_am_line(self):
        return SQL(
            """
            SELECT
                %s
            FROM
                %s
            WHERE
                %s
            """,
            self._select_am_line(),
            self._from_am_line(),
            self._where_am_line(),
        )

    @api.model
    def _select_am_line(self):
        return SQL(
            """
            -aml.id AS id,
            NULL::INTEGER AS pol_id,
            aml.id AS aml_id,
            aml.company_id,
            am.partner_id,
            aml.product_id,
            aml.quantity AS line_qty,
            aml.product_uom_id AS line_uom_id,
            NULL::NUMERIC AS qty_invoiced,
            NULL::NUMERIC AS qty_to_invoice,
            NULL::INTEGER AS purchase_order_id,
            am.id AS account_move_id,
            aml.amount_currency AS line_amount_taxexc,
            aml.currency_id,
            aml.parent_state AS state
            """,
        )

    @api.model
    def _from_am_line(self):
        return SQL(
            """
            account_move_line aml
            LEFT JOIN account_move am ON aml.move_id = am.id
            """,
        )

    @api.model
    def _where_am_line(self):
        return SQL(
            """
            aml.display_type = 'product'
            AND am.move_type IN ('in_invoice', 'in_refund')
            AND aml.parent_state IN ('draft', 'posted')
            AND NOT EXISTS (
                SELECT 1 FROM account_move_line_purchase_order_line_rel rel
                WHERE rel.move_line_id = aml.id
            )
            """,
        )
