from odoo import api, fields, models
from odoo.tools.sql import SQL


class SaleReport(models.Model):
    _inherit = "sale.report"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    order_reference = fields.Reference(
        selection_add=[("pos.order", "POS Order")],
    )
    state = fields.Selection(
        selection_add=[
            ("paid", "Paid"),
            ("invoiced", "Invoiced"),
            ("done", "Posted"),
        ],
    )

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    @api.model
    def _get_done_states(self):
        done_states = super()._get_done_states()
        done_states.extend(["paid", "invoiced", "done"])
        return done_states

    # ------------------------------------------------------------
    # QUERY METHODS
    # ------------------------------------------------------------

    @property
    def _table_query(self) -> SQL:
        """Override to add UNION ALL with POS orders.

        Returns:
            SQL: SQL object containing sale orders UNION ALL pos orders
        """
        sale_query = super()._table_query
        pos_query = SQL(
            "%s %s %s %s",
            self._select_pos(),
            self._from_pos(),
            self._where_pos(),
            self._group_by_pos(),
        )
        return SQL("( %s ) UNION ALL ( %s )", sale_query, pos_query)

    def _select_pos(self) -> SQL:
        """SELECT clause for POS orders in the sale report.

        Returns:
            SQL: SQL object containing the SELECT clause for POS data
        """
        currency_rate_pos = self._case_value_or_one("pos.currency_rate")
        currency_rate_table = self._case_value_or_one("account_currency_table.rate")

        base_select = SQL(
            """
            SELECT
                -MIN(l.id) AS id,
                CONCAT('pos.order', ',', pos.id) AS order_reference,
                pos.company_id AS company_id,
                %(currency_id)s AS currency_id,
                pos.partner_id AS partner_id,
                partner.commercial_partner_id AS commercial_partner_id,
                partner.country_id AS country_id,
                partner.state_id AS state_id,
                partner.zip AS partner_zip,
                partner.industry_id AS industry_id,
                pos.pricelist_id AS pricelist_id,
                pos.crm_team_id AS team_id,
                pos.user_id AS user_id,
                NULL AS campaign_id,
                NULL AS medium_id,
                NULL AS source_id,
                pos.date_order AS date_order,
                pos.name AS name,
                CASE WHEN pos.state = 'done'
                    THEN 'sale'
                    ELSE pos.state
                END AS state,
                NULL as invoice_state,
                NULL AS line_invoice_state,
                l.product_id AS product_id,
                p.product_tmpl_id,
                t.categ_id AS product_category_id,
                t.uom_id AS product_uom_id,
                SUM(l.qty) AS product_uom_qty,
                SUM(l.qty_transferred) AS qty_transferred,
                SUM(l.qty - l.qty_transferred) AS qty_to_transfer,
                CASE WHEN pos.account_move IS NOT NULL
                    THEN SUM(l.qty)
                    ELSE 0
                END AS qty_invoiced,
                CASE WHEN pos.account_move IS NULL
                    THEN SUM(l.qty)
                    ELSE 0
                END AS qty_to_invoice,
                AVG(l.price_unit)
                    / MIN(%(currency_rate_pos)s)
                    * %(currency_rate_table)s
                AS price_unit,
                SUM(l.price_subtotal)
                    / MIN(%(currency_rate_pos)s)
                    * %(currency_rate_table)s
                AS price_subtotal,
                SUM(l.price_subtotal_incl)
                    / MIN(%(currency_rate_pos)s)
                    * %(currency_rate_table)s
                AS price_total,
                l.discount AS discount,
                SUM(l.price_unit * l.discount * l.qty / 100.0
                    / %(currency_rate_pos)s
                    * %(currency_rate_table)s)
                AS discount_amount,
                (CASE WHEN pos.account_move IS NOT NULL
                    THEN SUM(l.price_subtotal)
                    ELSE 0
                END)
                    / MIN(%(currency_rate_pos)s)
                    * %(currency_rate_table)s
                AS amount_taxexc_invoiced,
                (CASE WHEN pos.account_move IS NULL
                    THEN SUM(l.price_subtotal)
                    ELSE 0
                END)
                    / MIN(%(currency_rate_pos)s)
                    * %(currency_rate_table)s
                AS amount_taxexc_to_invoice,
                SUM(p.weight * l.qty) AS weight,
                SUM(p.volume * l.qty) AS volume,
                COUNT(*) AS nbr_lines
            """,
            currency_rate_pos=SQL(currency_rate_pos),
            currency_rate_table=SQL(currency_rate_table),
            currency_id=self.env.company.currency_id.id,
        )

        # Add additional fields from hooks
        additional_fields = self._select_additional_fields()
        additional_fields_info = self._fill_pos_fields(additional_fields)
        additional_sql_parts = []
        for fname, value in additional_fields_info.items():
            additional_sql_parts.append(
                SQL(", %s AS %s", SQL(value), SQL.identifier(fname)),
            )

        if additional_sql_parts:
            return SQL("%s %s", base_select, SQL(" ").join(additional_sql_parts))

        return base_select

    def _from_pos(self) -> SQL:
        """FROM clause for POS orders in the sale report.

        Returns:
            SQL: SQL object containing the FROM clause for POS data
        """
        return SQL(
            """
            FROM
                pos_order_line l
                JOIN pos_order pos ON l.order_id = pos.id
                LEFT JOIN res_partner partner ON (pos.partner_id=partner.id OR pos.partner_id = NULL)
                LEFT JOIN product_product p ON l.product_id=p.id
                LEFT JOIN product_template t ON p.product_tmpl_id=t.id
                LEFT JOIN uom_uom u ON u.id=t.uom_id
                LEFT JOIN pos_session session ON session.id = pos.session_id
                LEFT JOIN pos_config config ON config.id = session.config_id
                LEFT JOIN stock_picking_type picking ON picking.id = config.picking_type_id
                JOIN %(currency_table)s ON account_currency_table.company_id = pos.company_id
            """,
            currency_table=self.env["res.currency"]._get_simple_currency_table(
                self.env.companies,
            ),
        )

    def _where_pos(self) -> SQL:
        """WHERE clause for POS orders in the sale report.

        Returns:
            SQL: SQL object containing the WHERE clause for POS data
        """
        return SQL(
            """
            WHERE
                l.sale_order_line_id IS NULL
            """,
        )

    def _group_by_pos(self) -> SQL:
        """GROUP BY clause for POS orders in the sale report.

        Returns:
            SQL: SQL object containing the GROUP BY clause for POS data
        """
        return SQL(
            """
            GROUP BY
                l.order_id,
                l.product_id,
                l.price_unit,
                l.discount,
                l.qty,
                t.uom_id,
                t.categ_id,
                pos.id,
                pos.name,
                pos.date_order,
                pos.partner_id,
                pos.user_id,
                pos.state,
                pos.company_id,
                pos.pricelist_id,
                p.product_tmpl_id,
                partner.commercial_partner_id,
                partner.country_id,
                partner.industry_id,
                partner.state_id,
                partner.zip,
                u.factor,
                pos.crm_team_id,
                account_currency_table.rate,
                picking.warehouse_id
            """,
        )

    def _available_additional_pos_fields(self):
        """Hook to replace the additional fields from sale with the one from pos_sale."""
        return {
            "warehouse_id": "picking.warehouse_id",
        }

    def _fill_pos_fields(self, additional_fields):
        """Hook to fill additional fields for the pos_sale.

        :param additional_fields: Dictionary mapping fields with their values
        :type additional_fields: dict[str, Any]
        """
        filled_fields = {x: "NULL" for x in additional_fields}
        for fname, value in self._available_additional_pos_fields().items():
            if fname in additional_fields:
                filled_fields[fname] = value
        return filled_fields
