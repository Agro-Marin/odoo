from odoo import api, fields, models
from odoo.tools.query import Query
from odoo.tools.sql import SQL


class PurchaseReport(models.Model):
    _name = "purchase.report"
    _description = "Purchase Report"
    _auto = False
    _rec_name = "date_order"
    _order = "date_order desc, price_total desc"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    nbr_lines = fields.Integer(
        string="# of Lines",
        readonly=True,
    )
    order_reference = fields.Reference(
        string="Order",
        selection=[("purchase.order", "Purchase Order")],
        aggregator="count_distinct",
    )
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
    commercial_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Commercial Entity",
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
    date_order = fields.Datetime(
        string="Order Date",
        readonly=True,
    )
    date_confirmed = fields.Datetime(
        string="Confirmation Date",
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft RFQ"),
            ("done", "Purchase Order"),
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
    qty_ordered = fields.Float(string="Qty Ordered", readonly=True)
    qty_transferred = fields.Float(string="Qty Received", readonly=True)
    qty_invoiced = fields.Float(string="Qty Billed", readonly=True)
    qty_to_invoice = fields.Float(string="Qty to be Billed", readonly=True)
    price_average = fields.Monetary(
        string="Average Cost",
        readonly=True,
        aggregator="avg",
    )
    price_total = fields.Monetary(string="Total", readonly=True)
    untaxed_total = fields.Monetary(string="Untaxed Total", readonly=True)
    delay = fields.Float(
        string="Days to Confirm",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
        help="Amount of time between purchase confirmation and order by date.",
    )
    delay_pass = fields.Float(
        string="Days to Receive",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
        help="Amount of time between date planned and order by date for each purchase order line.",
    )
    weight = fields.Float(string="Gross Weight", readonly=True)
    volume = fields.Float(string="Volume", readonly=True)

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    @api.readonly
    def action_view_order(self):
        """Open the purchase order form view from the report.

        Returns:
            dict: Action dictionary to open the order form view
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self.order_reference._name,
            "views": [[False, "form"]],
            "res_id": self.order_reference.id,
        }

    # ------------------------------------------------------------
    # QUERY METHODS
    # ------------------------------------------------------------

    @property
    def _table_query(self) -> SQL:
        """Report needs to be dynamic to take into account multi-company selected + multi-currency rates"""
        with_clause = self._with()
        if with_clause:
            return SQL(
                "WITH %s ( %s %s %s %s )",
                with_clause,
                self._select(),
                self._from(),
                self._where(),
                self._group_by(),
            )
        return SQL(
            "%s %s %s %s",
            self._select(),
            self._from(),
            self._where(),
            self._group_by(),
        )

    def _with(self) -> SQL:
        """Optional WITH clause for CTEs (Common Table Expressions).

        Returns:
            SQL: SQL object for WITH clause, or empty SQL for no CTE
        """
        return SQL("")

    def _select(self) -> SQL:
        """SELECT clause for the purchase report query.

        Returns:
            SQL: SQL object containing the SELECT clause with all fields and computations
        """
        base_select = SQL(
            """
            SELECT
                MIN(l.id) AS id,
                CONCAT('purchase.order', ',', o.id) AS order_reference,
                o.company_id AS company_id,
                c.currency_id,
                o.dest_address_id,
                o.partner_id AS partner_id,
                partner.commercial_partner_id AS commercial_partner_id,
                partner.country_id AS country_id,
                o.user_id AS user_id,
                o.fiscal_position_id AS fiscal_position_id,
                o.date_order AS date_order,
                o.date_confirmed,
                o.state,
                l.product_id,
                p.product_tmpl_id,
                t.categ_id AS product_category_id,
                t.uom_id AS product_uom_id,
                EXTRACT(
                    EPOCH FROM age(
                        o.date_confirmed, o.date_order
                    )
                ) / (24 * 60 * 60)::decimal(16,2) AS delay,
                EXTRACT(
                    EPOCH FROM age(
                        l.date_planned, o.date_order
                    )
                ) / (24 * 60 * 60)::decimal(16,2) AS delay_pass,
                SUM(
                    l.product_qty * line_uom.factor / product_uom.factor
                ) AS qty_ordered,
                SUM(
                    l.qty_transferred * line_uom.factor / product_uom.factor
                ) AS qty_transferred,
                SUM(
                    l.qty_invoiced * line_uom.factor / product_uom.factor
                ) AS qty_invoiced,
                CASE WHEN t.bill_policy = 'ordered'
                    THEN SUM(l.product_qty * line_uom.factor / product_uom.factor) - SUM(l.qty_invoiced * line_uom.factor / product_uom.factor)
                    ELSE SUM(l.qty_transferred * line_uom.factor / product_uom.factor) - SUM(l.qty_invoiced * line_uom.factor / product_uom.factor)
                END AS qty_to_invoice,
                (
                    SUM(
                        l.product_qty * l.price_unit / COALESCE(o.currency_rate, 1.0)
                    ) / NULLIF(
                        SUM(
                            l.product_qty * line_uom.factor / product_uom.factor
                        ),
                        0.0
                    )
                )::decimal(16,2) * account_currency_table.rate AS price_average,
                SUM(
                    l.price_total / COALESCE(o.currency_rate, 1.0)
                )::decimal(16,2) * account_currency_table.rate AS price_total,
                SUM(
                    p.weight * l.product_qty * line_uom.factor / product_uom.factor
                ) AS weight,
                SUM(
                    p.volume * l.product_qty * line_uom.factor / product_uom.factor
                ) AS volume,
                SUM(
                    l.price_subtotal / COALESCE(o.currency_rate, 1.0)
                )::decimal(16,2) * account_currency_table.rate AS untaxed_total,
                COUNT(*) AS nbr_lines
            """,
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

    def _from(self) -> SQL:
        """FROM clause for the purchase report query.

        Returns:
            SQL: SQL object containing the FROM clause with all necessary joins
        """
        return SQL(
            """
            FROM
                purchase_order_line l
                    JOIN purchase_order o ON (l.order_id=o.id)
                    JOIN res_partner partner ON o.partner_id = partner.id
                        LEFT JOIN product_product p ON (l.product_id=p.id)
                            LEFT JOIN product_template t ON (p.product_tmpl_id=t.id)
                    LEFT JOIN res_company C ON C.id = o.company_id
                    LEFT JOIN uom_uom line_uom ON (line_uom.id=l.product_uom_id)
                    LEFT JOIN uom_uom product_uom ON (product_uom.id=t.uom_id)
                    LEFT JOIN %(currency_table)s ON account_currency_table.company_id = o.company_id
            """,
            currency_table=self.env["res.currency"]._get_simple_currency_table(
                self.env.companies,
            ),
        )

    def _where(self) -> SQL:
        """WHERE clause for the purchase report query.

        Returns:
            SQL: SQL object containing the WHERE clause with filter conditions
        """
        return SQL(
            """
            WHERE
                l.display_type IS NULL
            """,
        )

    def _group_by(self) -> SQL:
        """GROUP BY clause for the purchase report query.

        Returns:
            SQL: SQL object containing the GROUP BY clause with all non-aggregated fields
        """
        return SQL(
            """
            GROUP BY
                o.company_id,
                o.user_id,
                o.partner_id,
                line_uom.factor,
                c.currency_id,
                l.price_unit,
                o.date_confirmed,
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

    def _select_additional_fields(self):
        """Hook to return additional fields SQL specification for select part of the table query.

        This method can be overridden by inheriting modules to add custom fields to the report.

        Returns:
            dict: Mapping field_name -> SQL computation of field

        Example:
            return {'custom_field': 'o.custom_column'}
        """
        return {}

    def _read_group_select(self, aggregate_spec: str, query: Query) -> SQL:
        """This override allows us to correctly calculate the average price of products."""
        if aggregate_spec != "price_average:avg":
            return super()._read_group_select(aggregate_spec, query)
        return SQL(
            "SUM(%(f_price)s * %(f_qty)s) / NULLIF(SUM(%(f_qty)s), 0.0)",
            f_qty=self._field_to_sql(self._table, "qty_ordered", query),
            f_price=self._field_to_sql(self._table, "price_average", query),
        )
