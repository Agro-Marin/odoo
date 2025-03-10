from odoo import api, fields, models, tools
from odoo.tools import formatLang


class PurchaseBillUnion(models.Model):
    _name = "purchase.bill.union"
    _description = "Purchases & Bills Union"
    _auto = False
    _order = "date desc, name desc"
    _rec_names_search = ["name", "reference"]

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Vendor",
        readonly=True,
    )
    vendor_bill_id = fields.Many2one(
        comodel_name="account.move",
        string="Vendor Bill",
        readonly=True,
    )
    purchase_order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Purchase Order",
        readonly=True,
    )
    name = fields.Char(string="Reference", readonly=True)
    reference = fields.Char(string="Source", readonly=True)
    date = fields.Date(string="Date", readonly=True)
    amount = fields.Float(string="Amount", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, "purchase_bill_union")
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW purchase_bill_union AS (
                SELECT
                    id, name, ref AS reference, partner_id, date, amount_untaxed AS amount, currency_id, company_id,
                    id AS vendor_bill_id, NULL AS purchase_order_id
                FROM
                    account_move
                WHERE
                    move_type='in_invoice'
                    AND state = 'posted'
            UNION
                SELECT
                    -id, name, partner_ref AS reference, partner_id, date_order::date AS date, amount_untaxed AS amount, currency_id, company_id,
                    NULL AS vendor_bill_id, id AS purchase_order_id
                FROM
                    purchase_order
                WHERE
                    state = 'purchase'
                    AND invoice_state IN ('to do', 'no')
            )
            """
        )

    @api.depends_context("show_total_amount")
    @api.depends("currency_id", "reference", "amount", "purchase_order_id")
    def _compute_display_name(self):
        for doc in self:
            name = doc.name or ""
            if doc.reference:
                name += " - " + doc.reference
            amount = doc.amount
            if doc.purchase_order_id and doc.purchase_order_id.invoice_state == "no":
                amount = 0.0
            name += ": " + formatLang(self.env, amount, currency_obj=doc.currency_id)
            doc.display_name = name
