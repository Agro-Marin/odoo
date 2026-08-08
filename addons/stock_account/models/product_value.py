from odoo import _, api, fields, models


class ProductValue(models.Model):
    """This model represents the history of manual update of a value.
    The potential update could be:
        - Modification of the product standard price
        - Modification of the lot standard price
        - Modification of the move value
    In case of modification of:
        - standard price, value contains the new standard price (by unit).
        - a move value: value contains the global value of the move.
    """

    _name = "product.value"
    _description = "Product Value"

    product_id = fields.Many2one("product.product", string="Product", index=True)
    lot_id = fields.Many2one("stock.lot", string="Lot")
    move_id = fields.Many2one("stock.move", string="Move", index="btree_not_null")

    value = fields.Monetary(string="Value", currency_field="currency_id", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        compute="_compute_company_id",
        store=True,
        required=True,
        precompute=True,
        readonly=False,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", string="Currency"
    )
    date = fields.Datetime(string="Date", default=fields.Datetime.now, required=True)
    user_id = fields.Many2one(
        "res.users", string="User", default=lambda self: self.env.user, required=True
    )

    description = fields.Char(string="Description")

    # User Display Fields
    current_value = fields.Monetary(
        string="Current Value", currency_field="currency_id", related="move_id.value"
    )
    current_value_details = fields.Char(
        string="Current Value Details", compute="_compute_current_value_details"
    )
    current_value_description = fields.Text(
        string="Current Value Description", compute="_compute_value_description"
    )
    computed_value_description = fields.Text(
        string="Computed Value Description", compute="_compute_value_description"
    )

    @api.depends("move_id", "lot_id", "product_id")
    def _compute_company_id(self):
        for product_value in self:
            if product_value.move_id:
                product_value.company_id = product_value.move_id.company_id
            elif product_value.lot_id:
                product_value.company_id = product_value.lot_id.company_id
            elif product_value.product_id:
                product_value.company_id = product_value.product_id.company_id
            else:
                product_value.company_id = self.env.company

    def _compute_current_value_details(self):
        for product_value in self:
            if not (product_value.move_id and product_value.move_id.quantity):
                product_value.current_value_details = False
                continue
            move = product_value.move_id
            quantity = move.quantity
            uom = move.product_uom_id.name
            price_unit = move.value / move.quantity
            product_value.current_value_details = _(
                "For %(quantity)s %(uom)s (%(price_unit)s per %(uom)s)",
                quantity=quantity,
                uom=uom,
                price_unit=price_unit,
            )

    def _compute_value_description(self):
        for product_value in self:
            if not product_value.move_id:
                product_value.current_value_description = False
                product_value.computed_value_description = False
                continue
            product_value.current_value_description = (
                product_value.move_id.value_justification
            )
            product_value.computed_value_description = (
                product_value.move_id.value_computed_justification
            )

    @api.model_create_multi
    def create(self, vals_list):
        product_ids = set()
        move_ids = set()
        lot_ids = set()

        # A manual revaluation is an input to the valuation engine
        # (`_run_average_batch` seeds from it), so the cost it implies has to reach
        # `standard_price`, which is what actually prices out-moves, COGS and
        # margins. `_change_standard_price` is the one caller that writes a row for
        # a price it has *already* set, and flags itself so its own record is not
        # recomputed back over -- a product-level row must not re-derive the
        # product's cost from lots that have not been updated yet.
        records_a_price_already_set = self.env.context.get("disable_auto_revaluation")
        for vals in vals_list:
            if vals.get("move_id"):
                move_ids.add(vals["move_id"])
            elif vals.get("lot_id") and vals.get("product_id"):
                # Revaluing one lot moves the product's average, so the product is
                # recomputed either way; only the lot itself is skipped when the
                # row simply records that lot's own new price.
                product_ids.add(vals["product_id"])
                if not records_a_price_already_set:
                    lot_ids.add(vals["lot_id"])
            elif vals.get("product_id") and not records_a_price_already_set:
                # Product-level rows used to miss this entirely -- the branch above
                # required a `lot_id` -- so a plain revaluation moved `total_value`
                # and `avg_cost` while `standard_price` stayed stale.
                product_ids.add(vals["product_id"])

        res = super().create(vals_list)
        if move_ids:
            self.env["stock.move"].browse(move_ids)._set_value()
        if product_ids:
            self.env["product.product"].browse(product_ids)._update_standard_price()
        if lot_ids:
            # `product._update_standard_price()` sets the *product's* cost; on a
            # lot-valuated product it never touches the lot, so a lot-level
            # revaluation has to be pushed to the lot it names as well.
            self.env["stock.lot"].browse(lot_ids).sudo()._update_standard_price()
        return res
