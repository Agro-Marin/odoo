from odoo import api, fields, models
from odoo.tools import SQL
from odoo.tools.query import Query

from odoo.addons.account.models.account_move import PAYMENT_STATE_SELECTION


class AccountInvoiceReport(models.Model):
    _name = "account.invoice.report"
    _description = "Invoices Statistics"
    _auto = False
    _order = "invoice_date desc"
    _rec_name = "invoice_date"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        readonly=True,
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Journal",
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Partner",
        readonly=True,
    )
    commercial_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Main Partner",
        readonly=True,
    )
    country_id = fields.Many2one(
        comodel_name="res.country",
        string="Country",
        readonly=True,
    )
    fiscal_position_id = fields.Many2one(
        comodel_name="account.fiscal.position",
        string="Fiscal Position",
        readonly=True,
    )
    invoice_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Salesperson",
        readonly=True,
    )
    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Entry",
        readonly=True,
    )
    move_type = fields.Selection(
        selection=[
            ("out_invoice", "Customer Invoice"),
            ("in_invoice", "Vendor Bill"),
            ("out_refund", "Customer Credit Note"),
            ("in_refund", "Vendor Credit Note"),
        ],
        string="Type",
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("posted", "Open"),
            ("cancel", "Cancelled"),
        ],
        string="Invoice Status",
        readonly=True,
    )
    payment_state = fields.Selection(
        selection=PAYMENT_STATE_SELECTION,
        string="Payment Status",
        readonly=True,
    )
    invoice_date = fields.Date(string="Invoice Date", readonly=True)
    invoice_date_due = fields.Date(string="Due Date", readonly=True)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        readonly=True,
    )
    product_category_id = fields.Many2one(
        comodel_name="product.category",
        string="Product Category",
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit",
        readonly=True,
    )

    account_id = fields.Many2one(
        comodel_name="account.account",
        string="Revenue/Expense Account",
        domain=[("deprecated", "=", False)],
        readonly=True,
    )

    quantity = fields.Float(string="Product Quantity", readonly=True)
    price_average = fields.Float(
        string="Average Price",
        readonly=True,
        aggregator="avg",
    )
    price_subtotal = fields.Float(string="Untaxed Amount", readonly=True)
    price_subtotal_currency = fields.Float(
        string="Untaxed Amount in Currency",
        readonly=True,
    )
    price_total = fields.Float(
        string="Total",
        readonly=True,
    )
    price_total_currency = fields.Float(
        string="Total in Currency",
        readonly=True,
    )
    inventory_value = fields.Float(string="Inventory Value", readonly=True)
    price_margin = fields.Float(string="Margin", readonly=True)

    _depends = {
        "account.move": [
            "name",
            "state",
            "move_type",
            "partner_id",
            "invoice_user_id",
            "fiscal_position_id",
            "invoice_date",
            "invoice_date_due",
            "invoice_payment_term_id",
            "partner_bank_id",
            "invoice_currency_rate",
        ],
        "account.move.line": [
            "quantity",
            "price_subtotal",
            "price_total",
            "amount_residual",
            "balance",
            "amount_currency",
            "move_id",
            "product_id",
            "product_uom_id",
            "account_id",
            "journal_id",
            "company_id",
            "currency_id",
            "partner_id",
        ],
        "product.product": ["product_tmpl_id", "standard_price"],
        "product.template": ["categ_id"],
        "uom.uom": ["factor", "name"],
        "res.currency.rate": ["currency_id", "name"],
        "res.partner": ["country_id"],
    }

    @property
    def _table_query(self) -> SQL:
        return self._query()

    def _query(self) -> SQL:
        return SQL(
            "SELECT %s FROM %s WHERE %s",
            self._select(),
            self._from(),
            self._where(),
        )

    @api.model
    def _select(self) -> SQL:
        return SQL(
            """
            line.id,
            line.move_id,
            move.company_id,
            move.journal_id,
            move.currency_id,
            move.commercial_partner_id,
            move.partner_id,
            COALESCE(partner.country_id, commercial_partner.country_id) AS country_id,
            move.fiscal_position_id,
            move.invoice_user_id,
            move.payment_state,
            move.invoice_date,
            move.invoice_date_due,
            move.move_type,
            move.state,
            line.account_id,
            account.account_type AS user_type,
            line.product_id,
            template.categ_id AS product_category_id,
            uom_template.id AS product_uom_id,
            (
                line.quantity
                / NULLIF(
                    COALESCE(uom_line.factor, 1) / COALESCE(uom_template.factor, 1),
                    0.0
                )
                * (
                    CASE
                    WHEN move.move_type IN ('in_invoice', 'out_refund', 'in_receipt')
                    THEN -1
                    ELSE 1
                    END
                )
            ) AS quantity,
            account_currency_table.rate * -line.balance AS price_subtotal,
            (
                line.price_subtotal
                * (
                    CASE
                    WHEN move.move_type IN ('in_invoice', 'out_refund', 'in_receipt')
                    THEN -1
                    ELSE 1
                    END
                )
            ) AS price_subtotal_currency,
            (
                line.price_total
                / move.invoice_currency_rate
                * (
                    CASE
                    WHEN move.move_type IN ('in_invoice', 'out_refund', 'in_receipt')
                    THEN -1
                    ELSE 1
                    END
                )
            ) AS price_total,
            (
                line.price_total
                * (
                    CASE
                    WHEN move.move_type IN ('in_invoice', 'out_refund', 'in_receipt')
                    THEN -1
                    ELSE 1
                    END
                )
            ) AS price_total_currency,
            (
                account_currency_table.rate
                * -COALESCE(
                    -- Average line price
                    (line.balance / NULLIF(line.quantity, 0.0))
                    -- convert to template uom
                    * (
                        NULLIF(COALESCE(uom_line.factor, 1), 0.0)
                        / NULLIF(COALESCE(uom_template.factor, 1), 0.0)
                    )
                    * (
                        CASE
                        WHEN move.move_type IN ('in_invoice', 'out_refund', 'in_receipt')
                        THEN -1
                        ELSE 1
                        END
                    ),
                    0.0
                )
            ) AS price_average,
            (
                account_currency_table.rate * line.quantity
                / NULLIF(
                    COALESCE(uom_line.factor, 1)
                    / COALESCE(uom_template.factor, 1),
                    0.0
                )
                * (
                    CASE
                    WHEN move.move_type IN ('out_invoice', 'in_refund', 'out_receipt')
                    THEN -1
                    ELSE 1
                    END
                )
                * COALESCE(product.standard_price -> line.company_id::text, to_jsonb(0.0))::float
            ) AS inventory_value,
            (    
                CASE
                WHEN move.move_type NOT IN ('out_invoice', 'out_receipt', 'out_refund')
                THEN 0.0
                WHEN move.move_type = 'out_refund'
                THEN
                    account_currency_table.rate
                    * (
                        -line.balance
                        + (
                            line.quantity
                            / NULLIF(
                                COALESCE(uom_line.factor, 1) / COALESCE(uom_template.factor, 1),
                                0.0
                            )
                        )
                        * COALESCE(product.standard_price -> line.company_id::text, to_jsonb(0.0))::float
                    )
                ELSE
                    account_currency_table.rate
                    * (
                        -line.balance
                        - (
                            line.quantity
                            / NULLIF(
                                COALESCE(uom_line.factor, 1)
                                / COALESCE(uom_template.factor, 1),
                                0.0
                            )
                        )
                        * COALESCE(product.standard_price -> line.company_id::text, to_jsonb(0.0))::float
                    )
                END
            ) AS price_margin
            """,
        )

    @api.model
    def _from(self) -> SQL:
        return SQL(
            """
            account_move_line line
            LEFT JOIN account_account account
                ON line.account_id=account.id
            LEFT JOIN uom_uom uom_line
                ON line.product_uom_id=uom_line.id
            LEFT JOIN product_product product
                ON line.product_id=product.id
                LEFT JOIN product_template template
                    ON product.product_tmpl_id=template.id
                    LEFT JOIN uom_uom uom_template
                        ON template.uom_id=uom_template.id
            INNER JOIN account_move move
                ON line.move_id=move.id
                LEFT JOIN res_partner commercial_partner
                    ON move.commercial_partner_id=commercial_partner.id
                LEFT JOIN res_partner partner
                    ON move.partner_id=partner.id
            JOIN %(currency_table)s
                ON line.company_id=account_currency_table.company_id
            """,
            currency_table=self.env["res.currency"]._get_simple_currency_table(
                self.env.companies
            ),
        )

    @api.model
    def _where(self) -> SQL:
        return SQL(
            """
            move.move_type IN ('out_invoice', 'out_refund', 'in_invoice', 'in_refund', 'out_receipt', 'in_receipt')
            AND line.account_id IS NOT NULL
            AND line.display_type = 'product'
            """,
        )

    def _read_group_select(self, aggregate_spec: str, query: Query) -> SQL:
        """This override allows us to correctly calculate the average price of products."""
        if aggregate_spec != "price_average:avg":
            return super()._read_group_select(aggregate_spec, query)

        return SQL(
            "COALESCE(SUM(%(f_price)s) / NULLIF(SUM(%(f_qty)s), 0.0), 0)",
            f_qty=self._field_to_sql(self._table, "quantity", query),
            f_price=self._field_to_sql(self._table, "price_subtotal", query),
        )


class ReportAccountReport_Invoice(models.AbstractModel):
    _name = "report.account.report_invoice"
    _description = "Account report without payment lines"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["account.move"].browse(docids)

        qr_code_urls = {}
        for invoice in docs:
            if invoice.display_qr_code:
                new_code_url = invoice._generate_qr_code(
                    silent_errors=data["report_type"] == "html"
                )
                if new_code_url:
                    qr_code_urls[invoice.id] = new_code_url

        return {
            "doc_ids": docids,
            "doc_model": "account.move",
            "docs": docs,
            "qr_code_urls": qr_code_urls,
        }


class ReportAccountReport_Invoice_With_Payments(models.AbstractModel):
    _name = "report.account.report_invoice_with_payments"
    _description = "Account report with payment lines"
    _inherit = ["report.account.report_invoice"]

    @api.model
    def _get_report_values(self, docids, data=None):
        rslt = super()._get_report_values(docids, data)
        rslt["report_type"] = data.get("report_type") if data else ""
        return rslt
