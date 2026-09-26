from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import frozendict


class PurchaseRequisition(models.Model):
    _name = "purchase.requisition"
    _inherit = ["mixin.agreement"]
    _description = "Purchase Requisition"

    agreement_type = fields.Selection(
        selection_add=[("purchase_template", "Purchase Template")],
        ondelete={"purchase_template": "cascade"},
    )
    user_id = fields.Many2one(string="Purchase Representative")
    order_count = fields.Count(
        count_of="order_ids",
        string="Number of Orders",
    )
    order_ids = fields.One2many(
        comodel_name="purchase.order",
        inverse_name="agreement_id",
        string="Purchase Orders",
    )
    line_ids = fields.One2many(
        comodel_name="purchase.requisition.line",
        inverse_name="agreement_id",
        string="Products to Purchase",
        copy=True,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        related="line_ids.product_id",
        string="Product",
    )

    def _get_sequence_code(self, agreement_type):
        return {
            "blanket_order": "purchase.requisition.blanket.order",
            "purchase_template": "purchase.requisition.purchase.template",
        }[agreement_type]

    def _get_partner_currency(self, partner):
        return partner.property_purchase_currency_id


class PurchaseRequisitionLine(models.Model):
    _name = "purchase.requisition.line"
    _inherit = ["mixin.agreement.line"]
    _description = "Purchase Requisition Line"
    _access_anchors = frozendict(
        {
            "company": models.Anchor("company_id", shared=False),
        }
    )

    product_id = fields.Many2one(domain=[("purchase_ok", "=", True)])
    product_description_variants = fields.Char(string="Description")
    price_unit = fields.Float(
        compute="_compute_price_unit",
        store=True,
        readonly=False,
    )
    agreement_id = fields.Many2one(
        comodel_name="purchase.requisition",
        string="Purchase Agreement",
        index=True,
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        related="agreement_id.company_id",
        string="Company",
        readonly=True,
    )
    supplier_info_ids = fields.One2many(
        comodel_name="product.supplierinfo",
        inverse_name="purchase_requisition_line_id",
    )

    @api.depends(
        "product_id",
        "company_id",
        "agreement_id.date_start",
        "product_qty",
        "product_uom_id",
        "agreement_id.partner_id",
        "agreement_id.agreement_type",
        "agreement_id.currency_id",
    )
    def _compute_price_unit(self):
        resolver = self.env["purchase.price.resolver"]
        for line in self:
            agreement = line.agreement_id
            if (
                agreement.state != "draft"
                or agreement.agreement_type != "purchase_template"
                or not agreement.partner_id
                or not line.product_id
            ):
                continue
            company = line.company_id or self.env.company
            seller = resolver._get_seller(
                line.product_id,
                partner=agreement.partner_id,
                quantity=line.product_qty,
                uom=line.product_uom_id,
                date=agreement.date_start,
                company=company,
                params={"force_uom": True},
            )
            line.price_unit = resolver._get_price_resolution(
                line.product_id,
                seller=seller,
                uom=line.product_uom_id or line.product_id.uom_id,
                currency=agreement.currency_id or company.currency_id,
                company=company,
                date=agreement.date_start or fields.Date.context_today(line),
                taxes=line.product_id.supplier_taxes_id,
            ).price_unit

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line, vals in zip(lines, vals_list, strict=True):
            if (
                line.agreement_id.agreement_type == "blanket_order"
                and line.agreement_id.state not in ["draft", "done", "cancel"]
            ):
                if line.price_unit <= 0.0:
                    raise UserError(
                        self.env._(
                            "You cannot have a negative or unit price of 0 for an already confirmed blanket order."
                        )
                    )
                supplier_infos = self.env["product.supplierinfo"].search(  # noqa: E8507 - one lookup per confirmed line, on its own product and vendor
                    [
                        ("product_id", "=", vals.get("product_id")),
                        ("partner_id", "=", line.agreement_id.partner_id.id),
                    ]
                )
                if not any(s.purchase_requisition_id for s in supplier_infos):
                    line._create_supplier_info()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if "price_unit" not in vals:
            return res
        if vals["price_unit"] <= 0.0 and any(
            agreement.agreement_type == "blanket_order"
            and agreement.state not in ["draft", "done", "cancel"]
            for agreement in self.mapped("agreement_id")
        ):
            raise UserError(
                self.env._(
                    "You cannot have a negative or unit price of 0 for an already confirmed blanket order."
                )
            )
        self.supplier_info_ids.write({"price": vals["price_unit"]})
        return res

    def unlink(self):
        to_unlink = self.filtered(
            lambda r: r.agreement_id.state not in ["draft", "done", "cancel"]
        )
        to_unlink.supplier_info_ids.unlink()
        return super().unlink()

    def _on_agreement_confirmed(self):
        for line in self:
            line._create_supplier_info()

    def _on_agreement_closed(self):
        self.supplier_info_ids.sudo().unlink()

    def _create_supplier_info(self):
        self.check_singleton()
        agreement = self.agreement_id
        if agreement.agreement_type == "blanket_order" and agreement.partner_id:
            self.env["product.supplierinfo"].sudo().create(
                {
                    "partner_id": agreement.partner_id.id,
                    "product_id": self.product_id.id,
                    "product_uom_id": self.product_uom_id.id,
                    "product_tmpl_id": self.product_id.product_tmpl_id.id,
                    "price": self.price_unit,
                    "currency_id": agreement.currency_id.id,
                    "date_start": agreement.date_start,
                    "date_end": agreement.date_end,
                    "purchase_requisition_line_id": self.id,
                }
            )

    def _add_description_variants(self, name):
        if not self or not self.product_description_variants:
            return name
        return name + "\n" + self.product_description_variants

    def _prepare_order_line_values(self, product_qty, tax_ids):
        values = super()._prepare_order_line_values(product_qty, tax_ids)
        date_commitment = fields.Datetime.now()
        if self.agreement_id.date_start:
            date_commitment = max(
                date_commitment,
                fields.Datetime.to_datetime(self.agreement_id.date_start),
            )
        values["date_commitment"] = date_commitment
        return values
