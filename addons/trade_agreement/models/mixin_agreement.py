from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class MixinAgreement(models.AbstractModel):
    _name = "mixin.agreement"
    _description = "Trade Agreement"
    _inherit = ["mixin.mail.thread", "mixin.mail.activity"]
    _order = "id desc"

    name = fields.Char(
        string="Agreement",
        default=lambda self: self.env._("New"),
        copy=False,
        readonly=True,
        required=True,
    )
    active = fields.Boolean(default=True)
    reference = fields.Char()
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        check_company=True,
    )
    agreement_type = fields.Selection(
        selection=[("blanket_order", "Blanket Order")],
        string="Agreement Type",
        default="blanket_order",
        required=True,
    )
    date_start = fields.Date(
        string="Start Date",
        tracking=True,
    )
    date_end = fields.Date(
        string="End Date",
        tracking=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        default=lambda self: self.env.user,
        check_company=True,
    )
    description = fields.Html()
    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
        required=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("done", "Closed"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="draft",
        copy=False,
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        compute="_compute_currency_id",
        precompute=True,
        store=True,
        readonly=False,
        required=True,
    )

    def _get_sequence_code(self, agreement_type):
        raise NotImplementedError(
            f"{self._name} must name the sequence of each agreement type"
        )

    def _get_partner_currency(self, partner):
        return self.env["res.currency"]

    @api.depends("partner_id")
    def _compute_currency_id(self):
        for agreement in self:
            agreement.currency_id = (
                agreement._get_partner_currency(agreement.partner_id)
                or agreement.company_id.currency_id
            )

    @api.onchange("partner_id")
    def _onchange_partner_id_open_blanket_order(self):
        if not self.partner_id:
            return None
        open_blanket_orders = self.search_count(
            [
                ("partner_id", "=", self.partner_id.id),
                ("state", "=", "confirmed"),
                ("agreement_type", "=", "blanket_order"),
                ("company_id", "=", self.company_id.id),
            ],
            limit=1,
        )
        if not open_blanket_orders:
            return None
        return {
            "warning": {
                "title": self.env._("Warning for %s", self.partner_id.name),
                "message": self.env._(
                    "There is already an open blanket order for this partner. We "
                    "suggest you complete this open blanket order, instead of "
                    "creating a new one."
                ),
            }
        }

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        invalid = self.filtered(
            lambda agreement: (
                agreement.date_end
                and agreement.date_start
                and agreement.date_end < agreement.date_start
            )
        )
        if invalid:
            raise ValidationError(
                self.env._(
                    "End date cannot be earlier than start date. Please check dates "
                    "for agreements: %s",
                    ", ".join(invalid.mapped("name")),
                )
            )

    def _next_name(self, agreement_type, company_id):
        return (
            self.env["ir.sequence"]
            .with_company(company_id)
            .next_by_code(self._get_sequence_code(agreement_type))
        )

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(["agreement_type", "company_id"])
        for vals in vals_list:
            vals["name"] = self._next_name(
                vals.get("agreement_type", defaults["agreement_type"]),
                vals.get("company_id", defaults["company_id"]),
            )
        return super().create(vals_list)

    def write(self, vals):
        to_rename = self.browse()
        if "agreement_type" in vals or "company_id" in vals:
            to_rename = self.filtered(
                lambda agreement: (
                    agreement.agreement_type
                    != vals.get("agreement_type", agreement.agreement_type)
                    or agreement.company_id.id
                    != vals.get("company_id", agreement.company_id.id)
                )
            )
        res = super().write(vals)
        for agreement in to_rename:
            if agreement.state != "draft":
                raise UserError(
                    self.env._(
                        "You cannot change the Agreement Type or Company of an "
                        "agreement that is not a draft."
                    )
                )
            if agreement.agreement_type != "blanket_order":
                agreement.date_start = agreement.date_end = False
            agreement.name = agreement._next_name(
                agreement.agreement_type, agreement.company_id.id
            )
        return res

    def unlink(self):
        self.line_ids.unlink()
        return super().unlink()

    @api.ondelete(at_uninstall=False)
    def _unlink_if_draft_or_cancel(self):
        if any(agreement.state not in ("draft", "cancel") for agreement in self):
            raise UserError(
                self.env._("You can only delete draft or cancelled agreements.")
            )

    def action_confirm(self):
        self.check_singleton()
        if not self.line_ids:
            raise UserError(
                self.env._(
                    "You cannot confirm agreement '%(agreement)s' because it does "
                    "not contain any product lines.",
                    agreement=self.name,
                )
            )
        if self.agreement_type == "blanket_order":
            if any(line.price_unit <= 0.0 for line in self.line_ids):
                raise UserError(
                    self.env._(
                        "You cannot confirm a blanket order with lines missing a price."
                    )
                )
            if any(line.product_qty <= 0.0 for line in self.line_ids):
                raise UserError(
                    self.env._(
                        "You cannot confirm a blanket order with lines missing a "
                        "quantity."
                    )
                )
        self.line_ids._on_agreement_confirmed()
        self.state = "confirmed"
        _debug.lifecycle("agreement_confirmed", agreement=self)

    def action_draft(self):
        self.check_singleton()
        self.state = "draft"

    def action_done(self):
        if any(order.state == "draft" for order in self.order_ids):
            raise UserError(
                self.env._(
                    "To close this agreement, cancel its related quotations first.\n\n"
                    "Imagine the mess if someone confirms these duplicates: double "
                    "the order, double the trouble :)"
                )
            )
        self.line_ids._on_agreement_closed()
        self.write({"state": "done"})
        _debug.lifecycle("agreements_closed", agreements=self)

    def action_cancel(self):
        self.line_ids._on_agreement_closed()
        for agreement in self:
            agreement.order_ids.action_cancel()
            for order in agreement.order_ids:
                order.message_post(
                    body=self.env._(
                        "Cancelled by the agreement associated to this quotation."
                    )
                )
        self.state = "cancel"
        _debug.lifecycle("agreements_cancelled", agreements=self)


class MixinAgreementLine(models.AbstractModel):
    _name = "mixin.agreement.line"
    _inherit = ["mixin.analytic"]
    _description = "Trade Agreement Line"
    _rec_name = "product_id"

    product_id = fields.Many2one(
        comodel_name="product.product",
        required=True,
    )
    product_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit",
        compute="_compute_product_uom_id",
        precompute=True,
        store=True,
        readonly=False,
    )
    product_qty = fields.Float(
        string="Quantity",
        digits="Product Unit",
    )
    price_unit = fields.Float(
        string="Unit Price",
        min_display_digits="Product Price",
    )
    qty_ordered = fields.Float(
        string="Ordered",
        compute="_compute_qty_ordered",
    )

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id

    @api.depends("agreement_id.order_ids.state")
    def _compute_qty_ordered(self):
        line_found = defaultdict(set)
        for line in self:
            total = 0.0
            for order in line.agreement_id.order_ids.filtered(
                lambda order: order.state == "done"
            ):
                for order_line in order.line_ids:
                    if order_line.product_id != line.product_id:
                        continue
                    total += order_line.product_uom_id._get_quantity_in_unit(
                        order_line.product_qty, line.product_uom_id
                    )
            if line.product_id not in line_found[line.agreement_id]:
                line.qty_ordered = total
                line_found[line.agreement_id].add(line.product_id)
            else:
                line.qty_ordered = 0

    def _on_agreement_confirmed(self):
        return None

    def _on_agreement_closed(self):
        return None

    def _prepare_order_line_values(self, product_qty, tax_ids):
        self.check_singleton()
        return {
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "product_qty": product_qty,
            "price_unit": self.price_unit,
            "tax_ids": [fields.Command.set(tax_ids)],
            "analytic_distribution": self.analytic_distribution,
        }
