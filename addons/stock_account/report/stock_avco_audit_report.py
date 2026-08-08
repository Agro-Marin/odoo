from odoo import fields, models
from odoo.db.schema import drop_view_if_exists

from odoo.addons.stock_account.models.avco import AvcoAccumulator


class StockAverageCostReport(models.AbstractModel):
    _auto = False
    _name = "stock.avco.report"
    _description = "Stock AVCO Justifier"
    # `id` is negated for product.value rows to stay unique across the UNION, so it
    # must never be used as a chronological tiebreak -- it would order adjustments
    # backwards and push all of them ahead of same-instant moves. `res_id` cannot
    # break ties across the two sources either (independent sequences), hence
    # `replay_rank`: at an equal timestamp the engine treats a revaluation as
    # landing after the move (`_run_average_batch` skips moves whose
    # `date <= product.value.date`), so the audit has to replay them in that order
    # or it would justify a different figure than the one actually stored.
    _order = "date desc, replay_rank desc, res_id desc"
    # Ascending counterpart of `_order`, used to replay the history forwards.
    _REPLAY_ORDER = "date, replay_rank, res_id"

    date = fields.Datetime(string="Date", required=True)
    replay_rank = fields.Integer(string="Replay Rank", required=True)
    res_id = fields.Integer(string="Resource ID", required=True)
    user_id = fields.Many2one("res.users", string="User", required=True)
    company_id = fields.Many2one("res.company", string="Company", required=True)
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Currency"
    )

    product_id = fields.Many2one("product.product", string="Product", required=True)

    reference = fields.Char(string="Reference", required=True)
    description = fields.Text(string="Description", required=True)

    res_model_name = fields.Selection(
        [
            ("stock.move", "Stock Move"),
            ("product.value", "Product Value"),
        ],
        string="Resource Model Name",
        required=True,
    )

    quantity = fields.Float(string="Added Quantity", required=True)
    value = fields.Float(string="Value", required=True)

    added_value = fields.Float(
        string="Added Value", compute="_compute_cumulative_fields"
    )
    total_quantity = fields.Float(
        string="Total Quantity", compute="_compute_cumulative_fields"
    )
    total_value = fields.Float(
        string="Total Value", compute="_compute_cumulative_fields"
    )
    avco_value = fields.Float(string="AVCO Value", compute="_compute_cumulative_fields")

    justification = fields.Text(
        string="Justification", compute="_compute_justification"
    )

    def init(self):
        drop_view_if_exists(self.env.cr, "stock_avco_report")
        query = """
CREATE OR REPLACE VIEW stock_avco_report AS (
SELECT
    sm.id AS id,
    sm.id AS res_id,
    0 AS replay_rank,
    sm.product_id,
    sm.date,
    picking.user_id,
    sm.company_id,
    sm.reference,
    CASE WHEN sm.is_in THEN sm.value ELSE -sm.value END AS value,
    CASE WHEN sm.is_in THEN sm.quantity * (um.factor / up.factor) ELSE -sm.quantity * (um.factor / up.factor) END AS quantity,
    'stock.move' AS res_model_name,
    'Operation' AS description
FROM
    stock_move sm
LEFT JOIN
    stock_picking picking ON sm.picking_id = picking.id
LEFT JOIN
    product_product pp ON sm.product_id = pp.id
LEFT JOIN
    product_template pt ON pp.product_tmpl_id = pt.id
LEFT JOIN
    product_category pc ON pt.categ_id = pc.id
LEFT JOIN
    res_company company ON sm.company_id = company.id
LEFT JOIN
    uom_uom um ON um.id = sm.product_uom_id
LEFT JOIN
    uom_uom up ON up.id = pt.uom_id
WHERE
    sm.state = 'done'
    AND (sm.is_in = TRUE OR sm.is_out = TRUE)
    -- Ignore moves valued at standard cost; for those only the cost updates matter.
    -- The effective method is the category's company-dependent value, falling back to
    -- the company default. Spelled as COALESCE because the equivalent OR-chain binds
    -- AND tighter than OR, which silently let every category-less product through.
    AND COALESCE(
        pc.property_cost_method ->> company.id::text,
        company.cost_method
    ) IN ('fifo', 'average')
UNION ALL
SELECT
    -pv.id,
    pv.id AS res_id,
    1 AS replay_rank,
    pv.product_id,
    pv.date,
    pv.user_id,
    pv.company_id,
    'Adjustment' AS reference, -- Set a fixed string for the reference
    pv.value,
    0 AS quantity, -- Set quantity to 0 as requested,
    'product.value' AS res_model_name,
    pv.description
FROM
    product_value pv
WHERE
    pv.move_id IS NULL
);
"""
        self.env.cr.execute(query)

    def _search(self, domain, *args, **kwargs):
        # This model is `_auto = False`, so the ORM's automatic flush -- which
        # targets the searched model -- flushes nothing at all. The view joins
        # stock_move, product_value, product_template, product_category,
        # res_company, stock_picking and uom_uom, and the cost-method filter reads
        # product_category, so a partial flush still hides rows: an unflushed
        # `property_cost_method` reads as NULL and silently drops every move for
        # that category. Flush everything -- this report exists to justify a
        # valuation, so reading around pending writes defeats its purpose.
        self.env.flush_all()
        return super()._search(domain, *args, **kwargs)

    def _compute_cumulative_fields(self):
        total_records_grouped = (
            self.env["stock.avco.report"]
            .search(
                [
                    ("product_id", "in", self.product_id.ids),
                    ("company_id", "in", self.company_id.ids),
                ]
            )
            .grouped(lambda m: (m.product_id, m.company_id))
        )
        for key, records in self.grouped(
            lambda m: (m.product_id, m.company_id)
        ).items():
            current_page_ids = set(records.ids)
            total_records = total_records_grouped.get(key, self.browse()).sorted(
                self._REPLAY_ORDER
            )
            # Replay the same AVCO recurrence as the live valuation engine
            # (product._run_average_batch) via the shared accumulator, so the audit
            # figures cannot drift from the actual valuation.
            avco = AvcoAccumulator(uom=records.product_id.uom_id)
            added_value = 0.0
            for record in total_records:
                if record.res_model_name == "stock.move":
                    if record.quantity > 0:
                        added_value = avco.add_in(record.quantity, record.value)
                    else:
                        added_value = -avco.add_out(-record.quantity)
                elif record.res_model_name == "product.value":
                    added_value = avco.set_unit_cost(record.value)

                if record.id in current_page_ids:
                    record.added_value = added_value
                    record.total_value = avco.value
                    record.total_quantity = avco.quantity
                    record.avco_value = avco.unit_cost

    def _compute_justification(self):
        self.justification = False
        for record in self:
            if record.res_model_name == "stock.move":
                record.justification = (
                    self.env["stock.move"].browse(record.res_id).value_justification
                )
