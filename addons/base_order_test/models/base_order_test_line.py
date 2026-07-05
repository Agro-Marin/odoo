from odoo import api, fields, models


class BaseOrderTestLine(models.Model):
    _name = "base.order.test.line"
    _inherit = [
        "order.line.fields.mixin",
        "order.line.amount.mixin",
        "order.line.invoice.mixin",
        "analytic.mixin",
    ]
    _description = "Base Order Test Line"

    # FIELDS

    order_id = fields.Many2one(
        comodel_name="base.order.test",
        string="Order",
        required=True,
        ondelete="cascade",
        index=True,
    )

    # Bridge fields the mixins expect the concrete model to supply
    # (real sale/purchase lines declare the same set).
    company_id = fields.Many2one(
        comodel_name="res.company",
        related="order_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        related="order_id.currency_id",
        store=True,
    )
    state = fields.Selection(
        related="order_id.state",
        store=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        related="order_id.partner_id",
        store=True,
    )
    locked = fields.Boolean(related="order_id.locked")
    # Self-referential section link: the compute lives in the mixin, but the
    # comodel must point to this concrete line model (as in sale/purchase).
    parent_id = fields.Many2one(
        comodel_name="base.order.test.line",
        string="Parent Section Line",
        compute="_compute_parent_id",
    )
    product_type = fields.Selection(related="product_id.type")
    product_categ_id = fields.Many2one(
        comodel_name="product.category",
        related="product_id.categ_id",
    )

    # ROUTING

    def _get_order_type(self):
        return "sale"

    # INVOICING METHODS

    # Concrete override of the two abstract stubs in order.line.invoice.mixin.
    # Kept deliberately trivial: enough for the shared computes/pipeline to run.
    @api.depends("product_qty", "price_unit")
    def _compute_invoice_amounts(self):
        for line in self:
            line.qty_invoiced = 0.0
            line.qty_to_invoice = line.product_qty or 0.0
            line.amount_taxexc_invoiced = 0.0
            line.amount_taxinc_invoiced = 0.0
            line.amount_taxexc_to_invoice = (line.product_qty or 0.0) * (
                line.price_unit or 0.0
            )
            line.amount_taxinc_to_invoice = line.amount_taxexc_to_invoice

    @api.depends("qty_to_invoice", "qty_invoiced")
    def _compute_invoice_state(self):
        for line in self:
            if line.display_type:
                line.invoice_state = "no"
            elif line.qty_to_invoice:
                line.invoice_state = "to do"
            else:
                line.invoice_state = "done"

    # ─── Hooks consumed by later tasks (trivial stubs) ─────────────

    def _get_default_line_description(self):
        return self.product_id.display_name or "/"

    def _get_auto_price_and_discount(self):
        self.ensure_one()
        return (self.product_id.list_price, 0.0)

    def _price_update_blocked(self):
        return False

    def _get_tracked_qty_fields(self):
        return ["product_qty"]

    def _post_quantity_changes(self, field_name, changes):
        for change in changes:
            change["line"].order_id.message_post(
                body=f"{field_name}: {change['old_qty']} -> {change['new_qty']}"
            )

    def _get_invoice_line_link_field(self):
        return None
