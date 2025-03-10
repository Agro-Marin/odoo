from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL
from odoo.tools.translate import _


class CrmTeam(models.Model):
    """Extends the 'crm.team' model to include sales-specific functionalities and metrics.

    This module enhances the CRM team model by adding fields and methods to track sales-related data,
    such as the number of quotations, sales to invoice, invoiced amounts, and sales targets. It also
    provides tools for analyzing sales performance and managing invoicing targets."""

    _inherit = "crm.team"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    invoiced_target = fields.Float(
        string="Invoicing Target",
        help="Revenue Target for the current month (untaxed total of paid invoices).",
    )
    amount_quotations = fields.Float(
        string="Amount of quotations to invoice",
        compute="_compute_quotations_to_invoice",
        readonly=True,
    )
    count_quotations = fields.Integer(
        string="Number of quotations to invoice",
        compute="_compute_quotations_to_invoice",
        readonly=True,
    )
    count_sale_order = fields.Integer(
        string="# Sale Orders",
        compute="_compute_count_sale_order",
    )
    count_sales_to_invoice = fields.Integer(
        string="Number of sales to invoice",
        compute="_compute_sales_to_invoice",
        readonly=True,
    )
    amount_invoiced_taxexc = fields.Float(
        string="Invoiced This Month",
        compute="_compute_sales_invoiced",
        readonly=True,
        help="Invoice revenue for the current month. This is the amount the sales "
        "channel has invoiced this month. It is used to compute the progression ratio "
        "of the current and target revenue on the kanban view.",
    )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.ondelete(at_uninstall=False)
    def _unlink_except_used_for_sales(self):
        """If more than 5 active SOs, we consider this team to be actively used.
        5 is some random guess based on "user testing", aka more than testing
        CRM feature and less than use it in real life use cases."""
        SO_COUNT_TRIGGER = 5
        for team in self:
            if team.count_sale_order >= SO_COUNT_TRIGGER:
                raise UserError(
                    _(
                        "Team %(team_name)s has %(count_sale_order)s active sale orders. "
                        "Consider cancelling them or archiving the team instead.",
                        team_name=team.name,
                        count_sale_order=team.count_sale_order,
                    )
                )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_quotations_to_invoice(self):
        query = self.env["sale.order"]._where_calc(
            [
                ("team_id", "in", self.ids),
                ("state", "=", "draft"),
            ]
        )
        self.env["sale.order"]._apply_ir_rules(query, "read")
        select_sql = SQL(
            """
            SELECT team_id, count(*), sum(amount_total /
                CASE COALESCE(currency_rate, 0)
                WHEN 0 THEN 1.0
                ELSE currency_rate
                END
            ) AS amount_total
            FROM
                sale_order
            WHERE
                %s
            GROUP BY
                team_id
            """,
            query.where_clause or SQL("TRUE"),
        )
        self.env.cr.execute(select_sql)
        quotation_data = self.env.cr.dictfetchall()
        teams = self.browse()
        for datum in quotation_data:
            team = self.browse(datum["team_id"])
            team.amount_quotations = datum["amount_total"]
            team.count_quotations = datum["count"]
            teams |= team
        remaining = self - teams
        remaining.amount_quotations = 0
        remaining.count_quotations = 0

    def _compute_count_sale_order(self):
        sale_order_data = self.env["sale.order"]._read_group(
            [
                ("team_id", "in", self.ids),
                ("state", "!=", "cancel"),
            ],
            ["team_id"],
            ["__count"],
        )
        data_map = {team.id: count for team, count in sale_order_data}
        for team in self:
            team.count_sale_order = data_map.get(team.id, 0)

    def _compute_sales_to_invoice(self):
        sale_order_data = self.env["sale.order"]._read_group(
            [
                ("team_id", "in", self.ids),
                ("invoice_state", "=", "to do"),
            ],
            ["team_id"],
            ["__count"],
        )
        data_map = {team.id: count for team, count in sale_order_data}
        for team in self:
            team.count_sales_to_invoice = data_map.get(team.id, 0.0)

    def _compute_sales_invoiced(self):
        if self.ids:
            today = fields.Date.today()
            data_map = dict(
                self.env.execute_query(
                    SQL(
                        """
                        SELECT
                            move.team_id AS team_id,
                            SUM(move.amount_untaxed_signed) AS amount_untaxed_signed
                        FROM
                            account_move move
                        WHERE
                            move.move_type IN ('out_invoice', 'out_refund', 'out_receipt')
                            AND move.payment_state IN ('in_payment', 'paid', 'reversed')
                            AND move.state = 'posted'
                            AND move.team_id IN %s
                            AND move.date BETWEEN %s AND %s
                        GROUP BY
                            move.team_id
                        """,
                        tuple(self.ids),
                        fields.Date.to_string(today.replace(day=1)),
                        fields.Date.to_string(today),
                    )
                )
            )
        else:
            data_map = {}
        for team in self:
            team.amount_invoiced_taxexc = data_map.get(team._origin.id, 0.0)

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_primary_channel_button(self):
        if self._in_sale_scope():
            return self.env["ir.actions.actions"]._for_xml_id(
                "sale.action_order_report_so_salesteam"
            )

        return super().action_primary_channel_button()

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _compute_dashboard_button_name(self):
        super()._compute_dashboard_button_name()
        if self._in_sale_scope():
            self.dashboard_button_name = _("Sales Analysis")

    def update_invoiced_target(self, value):
        return self.write({"invoiced_target": round(float(value or 0))})

    def _graph_date_column(self):
        if self._in_sale_scope():
            return SQL("date_order")
        return super()._graph_date_column()

    def _graph_get_model(self):
        if self._in_sale_scope():
            return "sale.report"
        return super()._graph_get_model()

    def _graph_get_table(self, GraphModel):
        if self._in_sale_scope():
            # For a team not shared between company, we make sure the amounts are expressed
            # in the currency of the team company and not converted to the current company currency,
            # as the amounts of the sale report are converted in the currency
            # of the current company (for multi-company reporting, see #83550)
            GraphModel = GraphModel.with_company(self.company_id)
            return SQL(f"({GraphModel._table_query}) AS {GraphModel._table}")
        return super()._graph_get_table(GraphModel)

    def _graph_title_and_key(self):
        if self._in_sale_scope():
            return ["", _("Sales: Untaxed Total")]  # no more title
        return super()._graph_title_and_key()

    def _graph_y_query(self):
        if self._in_sale_scope():
            return SQL("SUM(price_subtotal)")
        return super()._graph_y_query()

    def _extra_sql_conditions(self):
        if self._in_sale_scope():
            return SQL("state = 'sale'")
        return super()._extra_sql_conditions()

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

    def _in_sale_scope(self):
        return self.env.context.get("in_sales_app")
