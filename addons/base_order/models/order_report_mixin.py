from odoo import api, fields, models
from odoo.tools import SQL, Query


class OrderReportMixin(models.AbstractModel):
    """Analytical-report layer shared by sale.report and purchase.report.

    Sits between ``sql.report.mixin`` (which assembles the SQL from the
    ``_get_*`` registries) and the concrete order reports, and holds only what
    is genuinely identical for both: the display fields that carry no
    order-type wording, the line filter, the weighted-average aggregate and the
    "open the order" action.

    Everything whose *meaning* differs stays in the concrete report even where
    the two happened to be spelled the same — ``state`` is the example: both
    read ``fields.Selection(selection=const.ORDER_STATE, ...)``, but sale's
    labels are Quotation/Sales Order and purchase's are RFQ/Purchase Order.
    """

    _name = "order.report.mixin"
    _inherit = "sql.report.mixin"
    _description = "Order Analysis Report Base"
    _auto = False
    _rec_name = "date_order"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    # Placeholder so the ``Monetary`` fields below have a ``currency_field``
    # that resolves on the mixin itself at registry setup. The concrete reports
    # redeclare ``currency_id`` with their own attributes. Do not remove.

    currency_id = fields.Many2one("res.currency")

    nbr_lines = fields.Integer(
        string="# of Lines",
        readonly=True,
    )
    date_order = fields.Datetime(
        string="Order Date",
        readonly=True,
    )
    product_category_id = fields.Many2one(
        comodel_name="product.category",
        string="Product Category",
        readonly=True,
    )
    product_uom_qty = fields.Float(string="Qty Ordered", readonly=True)
    price_unit = fields.Float(string="Unit Price", aggregator="avg", readonly=True)
    price_subtotal = fields.Monetary(string="Untaxed Total", readonly=True)
    price_total = fields.Monetary(string="Total", readonly=True)
    weight = fields.Float(string="Gross Weight", readonly=True)
    volume = fields.Float(string="Volume", readonly=True)

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    @api.readonly
    def action_view_order(self):
        """Open the order this report line came from.

        Model-agnostic: ``order_reference`` is a Reference field, so it names
        its own model.
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self.order_reference._name,
            "views": [[False, "form"]],
            "res_id": self.order_reference.id,
        }

    # ------------------------------------------------------------
    # REGISTRY METHODS
    # ------------------------------------------------------------

    def _get_where_conditions(self) -> list:
        """Registry of conditions for the WHERE clause.

        :return: SQL condition strings that are AND'ed together
        :rtype: list
        """
        return [
            "l.display_type IS NULL",
        ]

    # ------------------------------------------------------------
    # AGGREGATES
    # ------------------------------------------------------------

    def _read_group_select(self, aggregate_spec: str, query: Query) -> SQL:
        """Compute the ``price_average:avg`` aggregate as a weighted average.

        A plain AVG over report rows weights every line equally, which is wrong
        once lines carry different quantities.
        """
        if aggregate_spec != "price_average:avg":
            return super()._read_group_select(aggregate_spec, query)
        return SQL(
            "SUM(%(f_price)s * %(f_qty)s) / NULLIF(SUM(%(f_qty)s), 0.0)",
            f_qty=self._field_to_sql(self._table, "product_uom_qty", query),
            f_price=self._field_to_sql(self._table, "price_average", query),
        )
