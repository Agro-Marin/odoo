from odoo import api, fields, models
from odoo.tools.sql import SQL

from odoo.addons.sale.models.sale_order import SALE_ORDER_STATE


class SaleReport(models.Model):
    _name = "sale.report"
    _description = "Sales Analysis Report"
    _auto = False
    _rec_name = "date_order"
    _order = "date_order desc"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    # aggregates or computed fields
    nbr_lines = fields.Integer(
        string="# of Lines",
        readonly=True,
    )
    order_reference = fields.Reference(
        string="Order",
        selection=[("sale.order", "Sales Order")],
        aggregator="count_distinct",
    )
    # sale.order fields
    company_id = fields.Many2one(
        comodel_name="res.company",
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        readonly=True,
    )
    # res.partner fields
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        readonly=True,
    )
    commercial_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer Entity",
        readonly=True,
    )
    country_id = fields.Many2one(
        comodel_name="res.country",
        string="Customer Country",
        readonly=True,
    )
    state_id = fields.Many2one(
        comodel_name="res.country.state",
        string="Customer State",
        readonly=True,
    )
    partner_zip = fields.Char(
        string="Customer ZIP",
        readonly=True,
    )
    industry_id = fields.Many2one(
        comodel_name="res.partner.industry",
        string="Customer Industry",
        readonly=True,
    )
    pricelist_id = fields.Many2one(
        comodel_name="product.pricelist",
        readonly=True,
    )
    team_id = fields.Many2one(
        comodel_name="crm.team",
        string="Sales Team",
        readonly=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Salesperson",
        readonly=True,
    )
    # utm fields
    campaign_id = fields.Many2one(
        comodel_name="utm.campaign",
        string="Campaign",
        readonly=True,
    )
    medium_id = fields.Many2one(
        comodel_name="utm.medium",
        string="Medium",
        readonly=True,
    )
    source_id = fields.Many2one(
        comodel_name="utm.source",
        string="Source",
        readonly=True,
    )
    date_order = fields.Datetime(
        string="Order Date",
        readonly=True,
    )
    name = fields.Char(
        string="Order Reference",
        readonly=True,
    )
    state = fields.Selection(
        selection=SALE_ORDER_STATE,
        string="Status",
        readonly=True,
    )
    invoice_state = fields.Selection(
        selection=[
            ("no", "Nothing to invoice"),
            ("to do", "To invoice"),
            ("partially", "Partially invoiced"),
            ("done", "Fully invoiced"),
            ("over done", "Upselling"),
        ],
        string="Order Invoice Status",
        readonly=True,
    )
    # sale.order.line fields
    line_invoice_state = fields.Selection(
        selection=[
            ("no", "Nothing to invoice"),
            ("to do", "To invoice"),
            ("partially", "Partially invoiced"),
            ("done", "Fully invoiced"),
            ("over done", "Upselling"),
        ],
        string="Invoice Status",
        readonly=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product Variant",
        readonly=True,
    )
    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
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
    product_uom_qty = fields.Float(string="Qty Ordered", readonly=True)
    qty_transferred = fields.Float(string="Qty Delivered", readonly=True)
    qty_to_transfer = fields.Float(string="Qty To Deliver", readonly=True)
    qty_invoiced = fields.Float(string="Qty Invoiced", readonly=True)
    qty_to_invoice = fields.Float(string="Qty To Invoice", readonly=True)
    price_unit = fields.Float(string="Unit Price", aggregator="avg", readonly=True)
    discount = fields.Float(string="Discount %", readonly=True, aggregator="avg")
    discount_amount = fields.Monetary(string="Discount Amount", readonly=True)
    price_subtotal = fields.Monetary(string="Untaxed Total", readonly=True)
    price_total = fields.Monetary(string="Total", readonly=True)
    amount_taxexc_invoiced = fields.Monetary(
        string="Untaxed Amount Invoiced",
        readonly=True,
    )
    amount_taxexc_to_invoice = fields.Monetary(
        string="Untaxed Amount To Invoice",
        readonly=True,
    )
    weight = fields.Float(string="Gross Weight", readonly=True)
    volume = fields.Float(string="Volume", readonly=True)

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    @api.readonly
    def action_view_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self.order_reference._name,
            "views": [[False, "form"]],
            "res_id": self.order_reference.id,
        }

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    @api.model
    def _get_done_states(self):
        return ["sale"]

    # ------------------------------------------------------------
    # QUERY METHODS
    # ------------------------------------------------------------

    @property
    def _table_query(self) -> SQL:
        """Report needs to be dynamic to take into account multi-company selected + multi-currency rates"""
        with_clause = self._with_sale()
        if with_clause:
            return SQL(
                "WITH %s ( %s %s %s %s )",
                with_clause,
                self._select_sale(),
                self._from_sale(),
                self._where_sale(),
                self._group_by_sale(),
            )
        return SQL(
            "%s %s %s %s",
            self._select_sale(),
            self._from_sale(),
            self._where_sale(),
            self._group_by_sale(),
        )

    def _with_sale(self) -> SQL:
        """Optional WITH clause for CTEs (Common Table Expressions).

        Returns:
            SQL: SQL object for WITH clause, or empty SQL for no CTE
        """
        return SQL("")

    def _select_sale(self) -> SQL:
        """SELECT clause for the sale report query.

        Returns:
            SQL: SQL object containing the SELECT clause with all fields and computations
        """
        currency_rate_o = self._case_value_or_one("o.currency_rate")
        currency_rate_table = self._case_value_or_one("account_currency_table.rate")

        base_select = SQL(
            """
            SELECT
                MIN(l.id) AS id,
                CONCAT('sale.order', ',', o.id) AS order_reference,
                o.company_id AS company_id,
                %(currency_id)s AS currency_id,
                o.partner_id AS partner_id,
                partner.commercial_partner_id AS commercial_partner_id,
                partner.country_id AS country_id,
                partner.state_id AS state_id,
                partner.zip AS partner_zip,
                partner.industry_id AS industry_id,
                o.pricelist_id AS pricelist_id,
                o.team_id AS team_id,
                o.user_id AS user_id,
                o.campaign_id AS campaign_id,
                o.medium_id AS medium_id,
                o.source_id AS source_id,
                o.date_order AS date_order,
                o.name AS name,
                o.state AS state,
                o.invoice_state AS invoice_state,
                l.invoice_state AS line_invoice_state,
                l.product_id AS product_id,
                p.product_tmpl_id,
                t.categ_id AS product_category_id,
                t.uom_id AS product_uom_id,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM(l.product_uom_qty * u.factor / u2.factor)
                    ELSE 0
                END AS product_uom_qty,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM(l.qty_transferred * u.factor / u2.factor)
                    ELSE 0
                END AS qty_transferred,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM((l.product_uom_qty - l.qty_transferred) * u.factor / u2.factor)
                    ELSE 0
                END AS qty_to_transfer,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM(l.qty_invoiced * u.factor / u2.factor)
                    ELSE 0
                END AS qty_invoiced,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM(l.qty_to_invoice * u.factor / u2.factor)
                    ELSE 0
                END AS qty_to_invoice,
                CASE WHEN l.product_id IS NOT NULL
                    THEN AVG(
                        l.price_unit
                        / %(currency_rate_o)s
                        * %(currency_rate_table)s
                    )
                    ELSE 0
                END AS price_unit,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM(
                        l.price_subtotal
                        / %(currency_rate_o)s
                        * %(currency_rate_table)s
                    )
                    ELSE 0
                END AS price_subtotal,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM(
                        l.price_total
                        / %(currency_rate_o)s
                        * %(currency_rate_table)s
                    )
                    ELSE 0
                END AS price_total,
                l.discount AS discount,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM(
                        l.price_unit * l.product_uom_qty * l.discount / 100.0
                        / %(currency_rate_o)s
                        * %(currency_rate_table)s
                    )
                    ELSE 0
                END AS discount_amount,
                CASE WHEN l.product_id IS NOT NULL OR l.is_downpayment
                    THEN SUM(
                        l.amount_taxexc_invoiced
                        / %(currency_rate_o)s
                        * %(currency_rate_table)s
                    )
                    ELSE 0
                END AS amount_taxexc_invoiced,
                CASE WHEN l.product_id IS NOT NULL OR l.is_downpayment
                    THEN SUM(
                        l.amount_taxexc_to_invoice
                        / %(currency_rate_o)s
                        * %(currency_rate_table)s
                    )
                    ELSE 0
                END AS amount_taxexc_to_invoice,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM(p.weight * l.product_uom_qty * u.factor / u2.factor)
                    ELSE 0
                END AS weight,
                CASE WHEN l.product_id IS NOT NULL
                    THEN SUM(p.volume * l.product_uom_qty * u.factor / u2.factor)
                    ELSE 0
                END AS volume,
                COUNT(*) AS nbr_lines
            """,
            currency_id=self.env.company.currency_id.id,
            currency_rate_o=SQL(currency_rate_o),
            currency_rate_table=SQL(currency_rate_table),
        )

        # Add additional fields from hooks
        additional_fields_info = self._select_additional_fields()
        additional_sql_parts = []
        for fname, query_info in additional_fields_info.items():
            additional_sql_parts.append(
                SQL(", %s AS %s", SQL(query_info), SQL.identifier(fname)),
            )

        if additional_sql_parts:
            return SQL("%s %s", base_select, SQL(" ").join(additional_sql_parts))

        return base_select

    def _from_sale(self) -> SQL:
        """FROM clause for the sale report query.

        Returns:
            SQL: SQL object containing the FROM clause with all necessary joins
        """
        return SQL(
            """
            FROM
                sale_order_line l
                LEFT JOIN sale_order o ON l.order_id=o.id
                JOIN res_partner partner ON o.partner_id=partner.id
                JOIN %(currency_table)s ON o.company_id=account_currency_table.company_id
                LEFT JOIN product_product p ON l.product_id=p.id
                LEFT JOIN product_template t ON p.product_tmpl_id=t.id
                LEFT JOIN uom_uom u2 ON t.uom_id=u2.id
                LEFT JOIN uom_uom u ON l.product_uom_id=u.id
            """,
            currency_table=self.env["res.currency"]._get_simple_currency_table(
                self.env.companies,
            ),
        )

    def _where_sale(self) -> SQL:
        """WHERE clause for the sale report query.

        Returns:
            SQL: SQL object containing the WHERE clause with filter conditions
        """
        return SQL(
            """
            WHERE
                l.display_type IS NULL
            """,
        )

    def _group_by_sale(self) -> SQL:
        """GROUP BY clause for the sale report query.

        Returns:
            SQL: SQL object containing the GROUP BY clause with all non-aggregated fields
        """
        return SQL(
            """
            GROUP BY
                l.product_id,
                l.order_id,
                l.price_unit,
                l.invoice_state,
                t.uom_id,
                t.categ_id,
                o.name,
                o.date_order,
                o.partner_id,
                o.user_id,
                o.state,
                o.invoice_state,
                o.company_id,
                o.campaign_id,
                o.medium_id,
                o.source_id,
                o.pricelist_id,
                o.team_id,
                p.product_tmpl_id,
                partner.commercial_partner_id,
                partner.country_id,
                partner.industry_id,
                partner.state_id,
                partner.zip,
                l.is_downpayment,
                l.discount,
                o.id,
                account_currency_table.rate
            """,
        )

    def _case_value_or_one(self, value):
        return f"""CASE COALESCE({value}, 0) WHEN 0 THEN 1.0 ELSE {value} END"""

    def _select_additional_fields(self):
        """Hook to return additional fields SQL specification for select part of the table query.

        This method can be overridden by inheriting modules to add custom fields to the report.

        Returns:
            dict: Mapping field_name -> SQL computation of field

        Example:
            return {'custom_field': 'o.custom_column'}
        """
        return {}
