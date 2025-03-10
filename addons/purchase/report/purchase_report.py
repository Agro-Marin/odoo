from odoo import fields, models
from odoo.tools.query import Query
from odoo.tools.sql import SQL


class PurchaseReport(models.Model):
    _name = "purchase.report"
    _description = "Purchase Analysis Report"
    _auto = False
    _order = "date_order desc, price_total desc"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

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
    order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Order",
        readonly=True,
    )
    # res.partner fields
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Vendor",
        readonly=True,
    )
    commercial_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Commercial Entity",
        readonly=True,
    )
    dest_address_id = fields.Many2one(
        comodel_name="res.partner",
        string="Delivery Address",
        readonly=True,
    )
    country_id = fields.Many2one(
        comodel_name="res.country",
        string="Partner Country",
        readonly=True,
    )
    fiscal_position_id = fields.Many2one(
        comodel_name="account.fiscal.position",
        string="Fiscal Position",
        readonly=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Buyer",
        readonly=True,
    )
    date_order = fields.Datetime("Order Date", readonly=True)
    date_approve = fields.Datetime("Confirmation Date", readonly=True)
    delay = fields.Float(
        string="Days to Confirm",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
        help="Amount of time between purchase approval and order by date.",
    )
    delay_pass = fields.Float(
        string="Days to Receive",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
        help="Amount of time between date planned and order by date for each purchase order line.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft RFQ"),
            ("purchase", "Purchase Order"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        readonly=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        readonly=True,
    )
    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        string="Product Template",
        readonly=True,
    )
    product_category_id = fields.Many2one(
        comodel_name="product.category",
        string="Product Category",
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Reference Unit of Measure",
        readonly=True,
    )
    qty_ordered = fields.Float("Qty Ordered", readonly=True)
    qty_transfered = fields.Float("Qty Received", readonly=True)
    qty_to_invoice = fields.Float("Qty to be Billed", readonly=True)
    qty_invoiced = fields.Float("Qty Billed", readonly=True)
    nbr_lines = fields.Integer("# of Lines", readonly=True)
    price_average = fields.Monetary("Average Cost", readonly=True, aggregator="avg")
    price_subtotal = fields.Monetary("Untaxed Total", readonly=True)
    price_total = fields.Monetary("Total", readonly=True)

    weight = fields.Float(string="Gross Weight", readonly=True)
    volume = fields.Float(string="Volume", readonly=True)

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    @property
    def _table_query(self) -> SQL:
        return self._query()

    def _query(self) -> SQL:
        return SQL(
            "SELECT %s FROM %s WHERE %s GROUP BY %s",
            self._select(),
            self._from(),
            self._where(),
            self._group_by(),
        )

    def _select(self) -> SQL:
        return SQL(
            """
            MIN(l.id) AS id,
            o.company_id AS company_id,
            c.currency_id,
            o.id AS order_id,
            o.partner_id AS partner_id,
            partner.commercial_partner_id AS commercial_partner_id,
            o.dest_address_id AS dest_address_id,
            partner.country_id AS country_id,
            o.fiscal_position_id AS fiscal_position_id,
            o.user_id AS user_id,
            o.date_order AS date_order,
            o.date_approve,
            (
                EXTRACT(epoch from age(o.date_approve,o.date_order))
                / (24*60*60)::decimal(16,2)
            ) AS delay,
            (
                EXTRACT(epoch from age(l.date_planned,o.date_order))
                / (24*60*60)::decimal(16,2)
            ) AS delay_pass,
            o.state,
            l.product_id,
            p.product_tmpl_id,
            t.categ_id AS product_category_id,
            t.uom_id AS product_uom_id,
            SUM(
                l.product_qty * line_uom.factor / product_uom.factor
            ) AS qty_ordered,
            (
                SUM(l.product_qty * l.price_unit / COALESCE(o.currency_rate, 1.0))
                / NULLIF(SUM(l.product_qty / line_uom.factor * product_uom.factor), 0.0)
            )::decimal(16,2) * account_currency_table.rate AS price_average,
            SUM(
                l.qty_transfered * line_uom.factor / product_uom.factor
            ) AS qty_transfered,
            CASE WHEN t.bill_policy = 'purchase'
                THEN
                    SUM(l.product_qty / line_uom.factor * product_uom.factor)
                    - SUM(l.qty_invoiced / line_uom.factor * product_uom.factor)
                ELSE
                    SUM(l.qty_transfered / line_uom.factor * product_uom.factor)
                    - SUM(l.qty_invoiced / line_uom.factor * product_uom.factor)
            END AS qty_to_invoice,
            SUM(
                l.qty_invoiced * line_uom.factor / product_uom.factor
            ) AS qty_invoiced,
            COUNT(*) AS nbr_lines,
            (
                SUM(l.price_subtotal / COALESCE(o.currency_rate, 1.0))::decimal(16,2)
                * account_currency_table.rate
            ) AS price_subtotal,
            (
                SUM(l.price_total / COALESCE(o.currency_rate, 1.0))::decimal(16,2)
                * account_currency_table.rate
            ) AS price_total,
            SUM(
                p.weight * l.product_qty / line_uom.factor * product_uom.factor
            ) AS weight,
            SUM(
                p.volume * l.product_qty / line_uom.factor * product_uom.factor
            ) AS volume
            """,
        )

    def _from(self) -> SQL:
        return SQL(
            """
            purchase_order_line l
            LEFT JOIN uom_uom line_uom
                ON l.product_uom_id=line_uom.id
            LEFT JOIN product_product p
                ON l.product_id=p.id
                LEFT JOIN product_template t
                    ON p.product_tmpl_id=t.id
                    LEFT JOIN uom_uom product_uom
                        ON t.uom_id=product_uom.id
            LEFT JOIN purchase_order o
                ON l.order_id=o.id
                LEFT JOIN res_partner partner
                    ON o.partner_id = partner.id
                LEFT JOIN res_company c
                    ON o.company_id = c.id
                LEFT JOIN %(currency_table)s
                    ON o.company_id = account_currency_table.company_id
            """,
            currency_table=self.env["res.currency"]._get_simple_currency_table(
                self.env.companies
            ),
        )

    def _where(self) -> SQL:
        return SQL(
            """
            l.display_type IS NULL
            """,
        )

    def _group_by(self) -> SQL:
        return SQL(
            """
            o.company_id,
            o.user_id,
            o.partner_id,
            line_uom.factor,
            c.currency_id,
            l.price_unit,
            o.date_approve,
            l.date_planned,
            l.product_uom_id,
            o.dest_address_id,
            o.fiscal_position_id,
            l.product_id,
            p.product_tmpl_id,
            t.categ_id,
            o.date_order,
            o.state,
            t.uom_id,
            t.bill_policy,
            line_uom.id,
            product_uom.factor,
            partner.country_id,
            partner.commercial_partner_id,
            o.id,
            account_currency_table.rate
            """,
        )

    def _read_group_select(self, aggregate_spec: str, query: Query) -> SQL:
        """This override allows us to correctly calculate
        the average price of products."""
        if aggregate_spec != "price_average:avg":
            return super()._read_group_select(aggregate_spec, query)

        return SQL(
            "SUM(%(f_price)s * %(f_qty)s) / NULLIF(SUM(%(f_qty)s), 0.0)",
            f_qty=self._field_to_sql(self._table, "qty_ordered", query),
            f_price=self._field_to_sql(self._table, "price_average", query),
        )
