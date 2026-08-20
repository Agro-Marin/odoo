from odoo import api, fields, models
from odoo.tools import SQL, Query


class MixinOrderReport(models.AbstractModel):
    """Analytical-report layer shared by sale.report and purchase.report.

    Sits between ``mixin.sql.report`` (which assembles the SQL from the
    ``_get_*`` registries) and the concrete order reports, and holds the line
    filter, the weighted-average aggregate, the "open the order" action, and
    the fields whose declarations are worth sharing.

    **Which fields those are.** A field is hoisted when what the two reports
    say about it *outweighs the one attribute that differs*. On a SQL-view
    report almost every field is ``comodel_name`` + ``readonly`` + a label, so
    hoisting one and relabelling it twice is close to a wash, and for the
    single-line ``Float`` columns (``qty_invoiced`` and friends) it is a net
    loss — two lines become three. Most of them therefore stay put, and that is
    a judgement about *field shape*, not about meaning.

    This is why the rule here reads as the opposite of ``mixin.order``'s, where
    ``partner_id`` and ``user_id`` *are* hoisted and relabelled: there the
    shared part is ``required``/``check_company``/``index``/``tracking`` on top
    of the comodel, so hoisting removes real duplication. Same rule, different
    field shapes, opposite answers. (An earlier version of this docstring said
    fields whose *meaning* differs must stay; applied to ``mixin.order`` that
    rule would forbid hoisting ``partner_id``, which is plainly right there.)

    ``state`` and ``order_reference`` are excluded for a third reason: their
    only substantive attribute is ``selection``, and it is exactly the one that
    differs (sale's labels are Quotation/Sales Order, purchase's RFQ/Purchase
    Order). Each report has to state it anyway, so a copy here would remove
    nothing.

    These are SQL views, so declaring a field here is only half of it — every
    consumer's ``_get_select_fields`` must also produce the column, which is
    what ``test_order_report`` checks by reading the hoisted fields back out of
    the built view rather than off the Python class.
    """

    _name = "mixin.order.report"
    _inherit = "mixin.sql.report"
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

    # Both reports declared this identically: purchase spelled out
    # ``string="Company"``, which is the label Odoo already derives from the
    # field name, so neither report needs to say anything about it.
    company_id = fields.Many2one(
        comodel_name="res.company",
        readonly=True,
    )
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
